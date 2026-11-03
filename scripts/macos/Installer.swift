// Per-user offline installer UI and pre-execution payload integrity checks.
import AppKit
import CryptoKit
import Darwin

let fm = FileManager.default
let hostName = "org.teacher.video_downloader"
struct InstallError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}
func fail(_ message: String) throws -> Never { throw InstallError(message: message) }
struct Payload: Codable {
    let schema: Int
    let target: String
    let version: String
    let prototype: Bool
    let firefoxID: String
    let files: [String: String]
}
func exists(_ path: URL) -> Bool {
    (try? path.resourceValues(forKeys: [.isSymbolicLinkKey])) != nil || fm.fileExists(atPath: path.path)
}
func safePath(_ value: String) -> Bool {
    !value.isEmpty && !value.hasPrefix("/") && value.split(separator: "/", omittingEmptySubsequences: false).allSatisfy { !$0.isEmpty && $0 != "." && $0 != ".." }
}
func noLinks(_ path: URL) throws {
    var part = URL(fileURLWithPath: "/", isDirectory: true)
    for name in path.standardizedFileURL.pathComponents.dropFirst() {
        part.appendPathComponent(name)
        if (try? part.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink) == true {
            try fail("A destination or payload uses a symbolic link. No files were replaced.")
        }
    }
}
func sha(_ path: URL) throws -> String {
    let handle = try FileHandle(forReadingFrom: path)
    defer { try? handle.close() }
    var hash = SHA256()
    while let bytes = try handle.read(upToCount: 1048576), !bytes.isEmpty { hash.update(data: bytes) }
    return hash.finalize().map { String(format: "%02x", $0) }.joined()
}
func validate(_ directory: URL) throws -> Payload {
    try noLinks(directory)
    let payload = try JSONDecoder().decode(Payload.self, from: Data(contentsOf: directory.appendingPathComponent("payload.json")))
    #if arch(arm64)
    let architecture = "arm64"
    #else
    let architecture = "x86_64"
    #endif
    guard payload.schema == 2, payload.target == "macos-" + (architecture == "arm64" ? "arm64" : "x64") else { try fail("This download is for a different Mac processor. Get the matching installer.") }
    guard ["teacher-video-downloader@local.invalid", "lessonshelf-preview@local.invalid"].contains(payload.firefoxID) else { try fail("Unapproved Firefox extension ID.") }
    let required = ["runtime/bin/python3", "tools/yt-dlp", "tools/ffmpeg", "tools/ffprobe", "companion/host.py", "companion/worker.py", "LICENSES.txt", "PROVENANCE.json", "installer/install_payload.py", "tools/N_m3u8DL-RE"]
    guard required.allSatisfy({ payload.files[$0] != nil }) else { try fail("The offline dependency bundle is incomplete. Get a complete installer.") }
    var actual = Set<String>()
    guard let walker = fm.enumerator(at: directory, includingPropertiesForKeys: [.isRegularFileKey, .isSymbolicLinkKey]) else { try fail("Cannot read payload.") }
    for case let path as URL in walker {
        let flags = try path.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey])
        guard flags.isSymbolicLink != true else { try fail("Payload symbolic links are not supported.") }
        if flags.isRegularFile == true { actual.insert(String(path.path.dropFirst(directory.path.count + 1))) }
    }
    guard actual == Set(payload.files.keys).union(["payload.json"]) else { try fail("The installer contains missing or unlisted files. Download it again.") }
    for (name, expected) in payload.files {
        guard safePath(name), expected.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil else { try fail("Invalid payload manifest.") }
        guard try sha(directory.appendingPathComponent(name)) == expected else { try fail("Installer integrity check failed. Download it again. Nothing was installed.") }
    }
    for name in required.prefix(4) {
        guard fm.isExecutableFile(atPath: directory.appendingPathComponent(name).path) else { try fail("An offline dependency is not executable.") }
    }
    return payload
}
func install(payload: URL, userRoot: URL, dryRun: Bool, staging: Bool) throws -> String {
    let spec = try validate(payload)
    guard staging || !spec.prototype else { try fail("This is a test-only payload. It can install only into an explicit staging directory.") }
    try noLinks(userRoot)
    let process = Process()
    process.executableURL = payload.appendingPathComponent("runtime/bin/python3")
    process.arguments = ["-B", "-I", payload.appendingPathComponent("installer/install_payload.py").path, "--payload", payload.path]
    if staging { process.arguments! += ["--stage-root", userRoot.path] } else { process.arguments! += ["--install"] }
    if dryRun { process.arguments!.append("--dry-run") }
    let stdout = Pipe(), stderr = Pipe()
    process.standardOutput = stdout; process.standardError = stderr
    try process.run()
    let output = stdout.fileHandleForReading.readDataToEndOfFile()
    let error = stderr.fileHandleForReading.readDataToEndOfFile()
    process.waitUntilExit()
    guard process.terminationStatus == 0 else { try fail(String(data: error, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "Installation failed. Try again.") }
    return staging ? (String(data: output, encoding: .utf8) ?? "Staging complete.") : "Installed. Return to LessonShelf in Firefox and choose Connect."
}

func runCLI() throws {
    let args = Array(CommandLine.arguments.dropFirst())
    guard args.count == 4 || args.count == 5, args[0] == "--payload", args[2] == "--stage-root", args.count == 4 || args[4] == "--dry-run" else { try fail("Usage: installer --payload DIRECTORY --stage-root EMPTY_TEST_ROOT [--dry-run]") }
    let root = URL(fileURLWithPath: args[3]).standardizedFileURL
    guard root.path != "/", root.path != fm.homeDirectoryForCurrentUser.path else { try fail("Staging requires a separate test directory.") }
    print(try install(payload: URL(fileURLWithPath: args[1]), userRoot: root, dryRun: args.contains("--dry-run"), staging: true))
}
if CommandLine.arguments.count > 1 {
    do { try runCLI() } catch { fputs("\(error.localizedDescription)\n", stderr); exit(1) }
} else {
    final class InstallerWindow: NSObject {
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 540, height: 290), styleMask: [.titled, .closable], backing: .buffered, defer: false)
        let status = NSTextField(wrappingLabelWithString: "Ready to install. Your queue and saved videos are kept. Close Firefox and wait for active downloads before an update.")
        let button = NSButton(title: "Install", target: nil, action: nil)
        let cancel = NSButton(title: "Cancel", target: nil, action: nil)
        let progress = NSProgressIndicator()
        var finished = false
        override init() {
            super.init()
            window.title = "Install LessonShelf companion"
            window.isReleasedWhenClosed = false
            window.backgroundColor = NSColor(red: 37/255, green: 36/255, blue: 34/255, alpha: 1)
            let title = NSTextField(labelWithString: "LessonShelf companion")
            title.font = NSFont.systemFont(ofSize: 23, weight: .semibold)
            title.frame = NSRect(x: 28, y: 227, width: 484, height: 35)
            let detail = NSTextField(wrappingLabelWithString: "Install for your Mac account and connect Firefox. All media tools are included. No administrator password is needed.")
            detail.frame = NSRect(x: 28, y: 155, width: 484, height: 60)
            status.frame = NSRect(x: 28, y: 74, width: 484, height: 75)
            for label in [title, detail, status] {
                label.textColor = NSColor(red: 1, green: 252/255, blue: 242/255, alpha: 1)
                if label !== title { label.font = NSFont.systemFont(ofSize: 14) }
                window.contentView!.addSubview(label)
            }
            button.frame = NSRect(x: 370, y: 22, width: 142, height: 40)
            button.bezelStyle = .rounded
            button.bezelColor = NSColor(red: 235/255, green: 94/255, blue: 40/255, alpha: 1)
            button.keyEquivalent = "\r"
            button.target = self; button.action = #selector(begin)
            cancel.frame = NSRect(x: 250, y: 22, width: 110, height: 40)
            cancel.bezelStyle = .rounded
            cancel.target = self; cancel.action = #selector(close)
            cancel.keyEquivalent = "\u{1b}"
            progress.style = .spinning
            progress.frame = NSRect(x: 28, y: 31, width: 24, height: 24)
            window.contentView!.addSubview(button); window.contentView!.addSubview(cancel); window.contentView!.addSubview(progress)
            window.center(); window.makeKeyAndOrderFront(nil)
        }
        @objc func close() { NSApplication.shared.terminate(nil) }
        @objc func begin() {
            if finished { close(); return }
            button.isEnabled = false; cancel.isEnabled = false
            window.standardWindowButton(.closeButton)?.isEnabled = false
            progress.startAnimation(nil)
            status.stringValue = "Checking and installing the bundled tools..."
            DispatchQueue.global(qos: .userInitiated).async {
                var message: String
                var success = false
                do {
                    guard let resources = Bundle.main.resourceURL else { try fail("Installer resources are missing.") }
                    message = try install(payload: resources.appendingPathComponent("payload"), userRoot: fm.homeDirectoryForCurrentUser, dryRun: false, staging: false)
                    success = true
                } catch { message = error.localizedDescription }
                DispatchQueue.main.async {
                    self.status.stringValue = message
                    self.finished = success
                    self.button.title = success ? "Close" : "Try again"
                    self.button.isEnabled = true; self.cancel.isEnabled = true
                    self.window.standardWindowButton(.closeButton)?.isEnabled = true
                    self.progress.stopAnimation(nil)
                }
            }
        }
    }
    let app = NSApplication.shared
    app.setActivationPolicy(.regular)
    app.appearance = NSAppearance(named: .darkAqua)
    let controller = InstallerWindow()
    app.activate(ignoringOtherApps: true)
    app.run()
    withExtendedLifetime(controller) {}
}
