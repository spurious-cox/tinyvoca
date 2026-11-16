// TinyVoca: a tester window for tiny-voca, the small text-to-speech model, plus the macOS system voices.
//
// The app is a web view around a small local Python server (gui.py). On first launch it builds the engine
// (a Python virtual environment with PyTorch and tiny-voca, plus the model weights) in
// ~/Library/Application Support/TinyVoca by running the bundled setup-engine.sh, showing its progress.
// After that it just starts the server on a free port, shows it, and stops it when the app quits.
import Cocoa
import WebKit

let appVersion = "1.1.0"
let tinyVocaGitHub = URL(string: "https://github.com/n4ze3m/tiny-voca")!
let tinyVocaWeights = URL(string: "https://huggingface.co/n4ze3m/tiny-voca")!
let tinyVocaDataset = URL(string: "https://huggingface.co/datasets/n4ze3m/tiny-voca")!
let tinyVocaDemo = URL(string: "https://tiny-voca.n4ze3m.com")!
let appGitHub = URL(string: "https://github.com/spurious-cox/tinyvoca")!

func freePort() -> Int {
    let s = socket(AF_INET, SOCK_STREAM, 0)
    defer { close(s) }
    var addr = sockaddr_in()
    addr.sin_family = sa_family_t(AF_INET)
    addr.sin_addr.s_addr = inet_addr("127.0.0.1")
    addr.sin_port = 0
    var len = socklen_t(MemoryLayout<sockaddr_in>.size)
    _ = withUnsafeMutablePointer(to: &addr) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(s, $0, len) }
    }
    _ = withUnsafeMutablePointer(to: &addr) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(s, $0, &len) }
    }
    return Int(UInt16(bigEndian: addr.sin_port))
}

func htmlEscape(_ s: String) -> String {
    s.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;").replacingOccurrences(of: ">", with: "&gt;")
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKDownloadDelegate, WKUIDelegate, WKScriptMessageHandler {
    var window: NSWindow!
    var web: WKWebView!
    var server: Process?
    var setup: Process?
    var setupTimer: Timer?
    var port = 0

    /// The engine folder. TINYVOCA_HOME overrides it (used for testing a clean first run).
    let root: URL = {
        if let h = ProcessInfo.processInfo.environment["TINYVOCA_HOME"], !h.isEmpty { return URL(fileURLWithPath: h) }
        return FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/TinyVoca")
    }()
    var pythonURL: URL { root.appendingPathComponent("venv/bin/python") }
    var readyURL: URL { root.appendingPathComponent(".ready") }
    var serverLog: URL { root.appendingPathComponent("gui.log") }
    var setupLog: URL { root.appendingPathComponent("setup.log") }

    func applicationDidFinishLaunching(_ n: Notification) {
        buildMenu()
        let cfg = WKWebViewConfiguration()
        cfg.mediaTypesRequiringUserActionForPlayback = []   // "Speak live" chains audio without a click each time
        cfg.userContentController.add(self, name: "save")   // "Save WAV…" posts {name, b64} here
        web = WKWebView(frame: .zero, configuration: cfg)
        web.navigationDelegate = self
        web.uiDelegate = self
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1100, height: 760),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable],
                          backing: .buffered, defer: false)
        window.title = "TinyVoca"
        window.contentView = web
        window.setFrameAutosaveName("TinyVocaWindow")
        if !window.setFrameUsingName("TinyVocaWindow") { window.center() }
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        begin()
    }

    // MARK: start-up

    func begin() {
        stopServer()
        do {
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
            // gui.py ships inside the app; the copy in the engine folder is refreshed on every launch.
            if let src = Bundle.main.url(forResource: "gui", withExtension: "py") {
                let dst = root.appendingPathComponent("gui.py")
                try? FileManager.default.removeItem(at: dst)
                try FileManager.default.copyItem(at: src, to: dst)
            }
        } catch {
            showMessage("Could not prepare the engine folder", htmlEscape(error.localizedDescription))
            return
        }
        if FileManager.default.fileExists(atPath: readyURL.path), FileManager.default.isExecutableFile(atPath: pythonURL.path) {
            showMessage("Loading the voice model…", "The first start after a launch takes a few seconds.")
            startServer()
        } else {
            runSetup()
        }
    }

    func showMessage(_ title: String, _ detail: String, log: Bool = false) {
        let html = """
        <meta name=color-scheme content="light dark"><body style="font:16px -apple-system;margin:0;display:grid;place-items:center;height:92vh">
        <div style="text-align:center;max-width:640px;padding:0 24px"><h2>\(title)</h2><p style="opacity:.75">\(detail)</p>
        \(log ? "<pre id=log style=\"text-align:left;font:12px ui-monospace,Menlo,monospace;opacity:.8;white-space:pre-wrap;max-height:40vh;overflow:hidden\"></pre>" : "")
        </div>
        """
        web.loadHTMLString(html, baseURL: nil)
    }

    func tail(_ url: URL, lines: Int) -> String {
        guard let data = try? Data(contentsOf: url), let s = String(data: data, encoding: .utf8) else { return "" }
        let cleaned = s.replacingOccurrences(of: "\r", with: "\n")
        return cleaned.split(separator: "\n", omittingEmptySubsequences: true).suffix(lines).joined(separator: "\n")
    }

    // MARK: first-run setup

    func runSetup() {
        guard let script = Bundle.main.url(forResource: "setup-engine", withExtension: "sh") else {
            showMessage("TinyVoca is damaged", "The setup script is missing from the app. Download TinyVoca again.")
            return
        }
        showMessage("Setting up TinyVoca (first launch only)",
                    "Downloading the speech model and its Python packages, about 300 MB. This takes a few minutes; please be patient.", log: true)
        FileManager.default.createFile(atPath: setupLog.path, contents: nil)
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/zsh")
        p.arguments = [script.path, root.path]
        if let h = try? FileHandle(forWritingTo: setupLog) { p.standardOutput = h; p.standardError = h }
        p.terminationHandler = { [weak self] proc in
            DispatchQueue.main.async { self?.setupFinished(proc) }
        }
        do { try p.run() } catch {
            showMessage("Could not start the setup", htmlEscape(error.localizedDescription))
            return
        }
        setup = p
        setupTimer = Timer.scheduledTimer(withTimeInterval: 0.7, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            let t = self.tail(self.setupLog, lines: 14)
            let js = "var e=document.getElementById('log');if(e)e.textContent=" + (String(data: (try? JSONSerialization.data(withJSONObject: [t], options: [])) ?? Data(), encoding: .utf8).map { String($0.dropFirst().dropLast()) } ?? "\"\"") + ";"
            self.web.evaluateJavaScript(js, completionHandler: nil)
        }
    }

    func setupFinished(_ proc: Process) {
        setupTimer?.invalidate(); setupTimer = nil
        guard setup === proc else { return }
        setup = nil
        if proc.terminationStatus == 0, FileManager.default.fileExists(atPath: readyURL.path) {
            showMessage("Loading the voice model…", "Almost there.")
            startServer()
        } else if proc.terminationStatus == 3 {
            showMessage("TinyVoca needs Python 3.10 or newer",
                        "Install it, for example with Homebrew (<code>brew install python</code>) or from python.org, then press ⌘R to try again.")
        } else {
            showMessage("The setup did not finish",
                        "Check your internet connection, then press ⌘R to try again.<br><br><small style=\"opacity:.7\">" + htmlEscape(tail(setupLog, lines: 6)).replacingOccurrences(of: "\n", with: "<br>") + "</small>")
        }
    }

    // MARK: speech server

    func startServer() {
        let script = root.appendingPathComponent("gui.py")
        guard FileManager.default.isExecutableFile(atPath: pythonURL.path), FileManager.default.fileExists(atPath: script.path) else {
            try? FileManager.default.removeItem(at: readyURL)
            showMessage("The engine is incomplete", "Press ⌘R to set it up again.")
            return
        }
        port = freePort()
        let p = Process()
        p.executableURL = pythonURL
        p.arguments = ["gui.py"]
        p.currentDirectoryURL = root
        var env = ProcessInfo.processInfo.environment
        env["PORT"] = String(port)
        env["PYTHONUNBUFFERED"] = "1"
        p.environment = env
        FileManager.default.createFile(atPath: serverLog.path, contents: nil)
        if let h = try? FileHandle(forWritingTo: serverLog) { p.standardOutput = h; p.standardError = h }
        p.terminationHandler = { [weak self] proc in
            DispatchQueue.main.async {
                guard let self = self, self.server === proc, proc.terminationReason != .uncaughtSignal || proc.terminationStatus != 15 else { return }
                let t = htmlEscape(self.tail(self.serverLog, lines: 4)).replacingOccurrences(of: "\n", with: "<br>")
                self.showMessage("The speech server stopped", t + "<br><br>Press ⌘R to start it again.")
            }
        }
        do { try p.run() } catch {
            showMessage("Could not start the server", htmlEscape(error.localizedDescription))
            return
        }
        server = p
        waitForServer(tries: 0)
    }

    func stopServer() {
        if let p = server { server = nil; if p.isRunning { p.terminate() } }
    }

    func waitForServer(tries: Int) {
        guard let p = server, p.isRunning else { return }
        let url = URL(string: "http://127.0.0.1:\(port)/info")!
        URLSession.shared.dataTask(with: url) { [weak self] data, _, _ in
            DispatchQueue.main.async {
                guard let self = self, self.server === p else { return }
                if data != nil {
                    self.web.load(URLRequest(url: URL(string: "http://127.0.0.1:\(self.port)/")!))
                } else if tries < 240 {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self.waitForServer(tries: tries + 1) }
                } else {
                    self.showMessage("The model did not load", "Press ⌘R to try again.")
                }
            }
        }.resume()
    }

    // MARK: web view delegates

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if action.shouldPerformDownload { decisionHandler(.download); return }
        // Links to the tiny-voca pages (or anywhere outside the local server) open in the default browser.
        if action.navigationType == .linkActivated, let url = action.request.url, url.host != "127.0.0.1" {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(.allow)
    }
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = suggestedFilename.isEmpty ? "tiny-voca.wav" : suggestedFilename
        panel.beginSheetModal(for: window) { r in completionHandler(r == .OK ? panel.url : nil) }
    }
    // "Save WAV…": the page hands over the audio (base64) and the app shows the Save panel.
    func userContentController(_ ucc: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == "save", let body = message.body as? [String: Any],
              let b64 = body["b64"] as? String, let data = Data(base64Encoded: b64) else { return }
        let panel = NSSavePanel()
        panel.nameFieldStringValue = (body["name"] as? String) ?? "tiny-voca.wav"
        panel.allowedFileTypes = ["wav"]
        panel.beginSheetModal(for: window) { r in
            guard r == .OK, let url = panel.url else { return }
            do { try data.write(to: url) } catch {
                let a = NSAlert(); a.messageText = "Could not save the file"; a.informativeText = error.localizedDescription; a.runModal()
            }
        }
    }
    // "Open text file…": the web view's file input needs the app to show the Open panel.
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        panel.message = "Choose a plain text file to load into the text box"
        panel.beginSheetModal(for: window) { r in completionHandler(r == .OK ? panel.urls : nil) }
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { NSWorkspace.shared.open(url) }
        return nil
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        let a = NSAlert()
        a.messageText = message
        a.addButton(withTitle: "OK"); a.addButton(withTitle: "Cancel")
        completionHandler(a.runModal() == .alertFirstButtonReturn)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ app: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ n: Notification) {
        stopServer()
        if let p = setup, p.isRunning { p.terminate() }
    }

    // MARK: menus

    func buildMenu() {
        let main = NSMenu()
        func item(_ menu: NSMenu, _ title: String, _ sel: Selector?, _ key: String, _ mods: NSEvent.ModifierFlags = .command) {
            let i = NSMenuItem(title: title, action: sel, keyEquivalent: key)
            i.keyEquivalentModifierMask = mods
            menu.addItem(i)
        }
        let appItem = NSMenuItem(); main.addItem(appItem)
        let appMenu = NSMenu(); appItem.submenu = appMenu
        item(appMenu, "About TinyVoca", #selector(about), "")
        appMenu.addItem(.separator())
        item(appMenu, "Hide TinyVoca", #selector(NSApplication.hide(_:)), "h")
        appMenu.addItem(.separator())
        item(appMenu, "Quit TinyVoca", #selector(NSApplication.terminate(_:)), "q")
        let editItem = NSMenuItem(); main.addItem(editItem)
        let edit = NSMenu(title: "Edit"); editItem.submenu = edit
        item(edit, "Undo", Selector(("undo:")), "z")
        item(edit, "Redo", Selector(("redo:")), "Z", [.command, .shift])
        edit.addItem(.separator())
        item(edit, "Cut", #selector(NSText.cut(_:)), "x")
        item(edit, "Copy", #selector(NSText.copy(_:)), "c")
        item(edit, "Paste", #selector(NSText.paste(_:)), "v")
        item(edit, "Select All", #selector(NSText.selectAll(_:)), "a")
        let viewItem = NSMenuItem(); main.addItem(viewItem)
        let view = NSMenu(title: "View"); viewItem.submenu = view
        item(view, "Reload", #selector(reload), "r")
        let helpItem = NSMenuItem(); main.addItem(helpItem)
        let help = NSMenu(title: "Help"); helpItem.submenu = help
        item(help, "tiny-voca on GitHub", #selector(openGitHub), "")
        item(help, "tiny-voca model on Hugging Face", #selector(openWeights), "")
        item(help, "tiny-voca dataset", #selector(openDataset), "")
        item(help, "tiny-voca web demo", #selector(openDemo), "")
        help.addItem(.separator())
        item(help, "TinyVoca on GitHub", #selector(openApp), "")
        NSApp.mainMenu = main
        NSApp.helpMenu = help
    }
    @objc func reload() {
        if setup != nil { return }
        if server?.isRunning == true, web.url?.host == "127.0.0.1" { web.reload() } else { begin() }
    }
    @objc func openGitHub() { NSWorkspace.shared.open(tinyVocaGitHub) }
    @objc func openWeights() { NSWorkspace.shared.open(tinyVocaWeights) }
    @objc func openDataset() { NSWorkspace.shared.open(tinyVocaDataset) }
    @objc func openDemo() { NSWorkspace.shared.open(tinyVocaDemo) }
    @objc func openApp() { NSWorkspace.shared.open(appGitHub) }
    @objc func about() {
        let credits = NSMutableAttributedString(string: "A tester window for tiny-voca by Muhammed Nazeem (n4ze3m), plus the macOS system voices.\n\n")
        for (label, url) in [("tiny-voca on GitHub", tinyVocaGitHub), ("Model weights", tinyVocaWeights), ("Dataset", tinyVocaDataset), ("Web demo", tinyVocaDemo)] {
            credits.append(NSAttributedString(string: label + "\n", attributes: [.link: url]))
        }
        NSApp.orderFrontStandardAboutPanel(options: [.applicationName: "TinyVoca", .applicationVersion: appVersion, .credits: credits])
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = AppDelegate()
app.delegate = delegate
app.run()
