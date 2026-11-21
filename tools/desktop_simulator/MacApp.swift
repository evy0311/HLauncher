import AppKit
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate, WKScriptMessageHandler {
    var window: NSWindow!
    var web: WKWebView!
    var backend: Process?
    var timer: Timer?
    var ready: URL!
    var config: [String: String] = [:]
    var log: URL!
    var generation = 0

    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            let path = Bundle.main.url(forResource: "simulator", withExtension: "json")!
            config = try JSONSerialization.jsonObject(with: Data(contentsOf: path)) as! [String: String]
            let menu = NSMenu()
            let appItem = NSMenuItem(); menu.addItem(appItem)
            let appMenu = NSMenu(); appItem.submenu = appMenu
            appMenu.addItem(withTitle: "Reload Python UI", action: #selector(reload), keyEquivalent: "r").target = self
            appMenu.addItem(NSMenuItem.separator())
            appMenu.addItem(withTitle: "Quit HLauncher Simulator", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
            let editItem = NSMenuItem(); menu.addItem(editItem)
            let editMenu = NSMenu(title: "Edit"); editItem.submenu = editMenu
            for (title, selector, key) in [("Undo", "undo:", "z"), ("Cut", "cut:", "x"), ("Copy", "copy:", "c"), ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")] {
                editMenu.addItem(withTitle: title, action: Selector(selector), keyEquivalent: key)
            }
            NSApp.mainMenu = menu
            let content = WKWebViewConfiguration()
            content.userContentController.add(self, name: "screenshot")
            web = WKWebView(frame: .zero, configuration: content)
            if #available(macOS 13.3, *) { web.isInspectable = true }
            window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1160, height: 820), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
            window.title = "HLauncher Simulator"
            window.minSize = NSSize(width: 960, height: 680)
            window.contentView = web; window.delegate = self
            window.center(); window.makeKeyAndOrderFront(nil)
            if let repo = config["repo"] { NSApp.applicationIconImage = NSImage(contentsOfFile: repo + "/hlauncher/ui/assets/branding/hlauncher-512.png") }
            NSApp.activate(ignoringOtherApps: true)
            try startBackend()
        } catch { showError(String(describing: error)) }
    }
    func showError(_ message: String) {
        let alert = NSAlert(); alert.messageText = "Could not start HLauncher Simulator"
        alert.informativeText = message; alert.runModal()
    }
    func startBackend() throws {
        generation += 1
        let current = generation
        let temp = FileManager.default.temporaryDirectory.appendingPathComponent("hlauncher-simulator-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: temp, withIntermediateDirectories: true)
        ready = temp.appendingPathComponent("ready.txt"); log = temp.appendingPathComponent("backend.log")
        FileManager.default.createFile(atPath: log.path, contents: nil)
        let output = try FileHandle(forWritingTo: log)
        let process = Process()
        process.executableURL = URL(fileURLWithPath: config["python"]!)
        process.currentDirectoryURL = URL(fileURLWithPath: config["repo"]!)
        process.arguments = ["-m", "tools.desktop_simulator", "--ready-file", ready.path]
        if let state = config["state"] { process.arguments! += ["--state-dir", state] }
        process.standardOutput = output; process.standardError = output
        try process.run(); backend = process
        var tries = 0
        timer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] timer in
            guard let self = self, current == self.generation else { timer.invalidate(); return }
            tries += 1
            if let text = try? String(contentsOf: self.ready, encoding: .utf8), let url = URL(string: text) {
                timer.invalidate(); self.web.load(URLRequest(url: url))
            } else if !process.isRunning || tries > 150 {
                timer.invalidate()
                if process.isRunning { process.interrupt() }
                let details = (try? String(contentsOf: self.log, encoding: .utf8)) ?? "No backend log"
                self.showError(details + "\nRebuild the app after moving the repository or Python installation.")
            }
        }
    }
    @objc func reload() {
        timer?.invalidate()
        if let process = backend, process.isRunning { process.interrupt(); process.waitUntilExit() }
        do { try startBackend() } catch { showError(String(describing: error)) }
    }
    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let raw = message.body as? String, let data = Data(base64Encoded: raw) else { return }
        let panel = NSSavePanel(); panel.nameFieldStringValue = "hlauncher-simulator.png"
        panel.beginSheetModal(for: window) { result in
            if result == .OK, let url = panel.url { try? data.write(to: url) }
        }
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationWillTerminate(_ notification: Notification) {
        timer?.invalidate()
        if let process = backend, process.isRunning { process.interrupt(); process.waitUntilExit() }
    }
}
let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = AppDelegate()
app.delegate = delegate
app.run()
