// Local prototype. No privileged operations, network requests, or update replacement.
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
    let architecture: String
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
    guard payload.schema == 1, payload.architecture == architecture else { try fail("This download is for a different Mac processor. Get the matching installer.") }
    guard ["teacher-video-downloader@local.invalid", "lessonshelf-preview@local.invalid"].contains(payload.firefoxID) else { try fail("Unapproved Firefox extension ID.") }
    let required = ["runtime/bin/python3", "tools/yt-dlp", "tools/ffmpeg", "tools/ffprobe", "companion/host.py", "companion/worker.py", "LICENSES.txt"]
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
func quote(_ value: String) -> String { "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'" }
func install(payload: URL, userRoot: URL, dryRun: Bool, staging: Bool) throws -> String {
    let spec = try validate(payload)
    guard staging || !spec.prototype else { try fail("This is a test-only prototype. It can install only into an explicit staging directory.") }
    try noLinks(userRoot)
    let base = userRoot.appendingPathComponent("Library/Application Support/Teacher Video Downloader")
    let app = base.appendingPathComponent("app")
    let manifest = userRoot.appendingPathComponent("Library/Application Support/Mozilla/NativeMessagingHosts/\(hostName).json")
    try noLinks(app); try noLinks(manifest)
    guard !exists(app), !exists(manifest) else { try fail("A companion or browser registration already exists. Nothing was replaced. Keep using your current companion.") }
    if dryRun { return "Ready to install into \(userRoot.path). No files changed." }
    // mkdir is the exclusive lock. Never remove a lock owned by another installer.
    try fm.createDirectory(at: base, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
    let lock = base.appendingPathComponent(".installer-lock")
    guard mkdir(lock.path, 0o700) == 0 else { try fail("Another installation is running, or an interrupted installation needs review. Nothing was replaced.") }
    var keepLock = false
    defer { if !keepLock { try? fm.removeItem(at: lock) } }
    let staged = lock.appendingPathComponent("app")
    var installed = false
    do {
        try fm.copyItem(at: payload, to: staged)
        _ = try validate(staged)
        let launcher = staged.appendingPathComponent("launch-host")
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.withoutEscapingSlashes]
        let companion = String(data: try encoder.encode(app.appendingPathComponent("companion").path), encoding: .utf8)!
        let host = String(data: try encoder.encode(app.appendingPathComponent("companion/host.py").path), encoding: .utf8)!
        let bootstrap = "import runpy,sys;sys.path.insert(0," + companion + ");runpy.run_path(" + host + ",run_name='__main__')"
        let script = "#!/bin/sh\numask 077\nexport PATH=" + quote(app.appendingPathComponent("tools").path + ":/usr/bin:/bin") + "\nexport PYTHONNOUSERSITE=1\nunset PYTHONPATH PYTHONHOME\nexec " + quote(app.appendingPathComponent("runtime/bin/python3").path) + " -I -c " + quote(bootstrap) + " \"$@\"\n"
        try script.write(to: launcher, atomically: false, encoding: .utf8)
        try fm.setAttributes([.posixPermissions: 0o700], ofItemAtPath: launcher.path)
        try fm.createDirectory(at: manifest.deletingLastPathComponent(), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        // Recheck after copying. moveItem refuses an existing app; link refuses a manifest race.
        try noLinks(app); try noLinks(manifest)
        guard !exists(app), !exists(manifest) else { try fail("An installation appeared while preparing. Nothing was replaced.") }
        try fm.moveItem(at: staged, to: app); installed = true
        let registration: [String: Any] = ["name": hostName, "description": "LessonShelf local companion", "type": "stdio", "path": app.appendingPathComponent("launch-host").path, "allowed_extensions": [spec.firefoxID]]
        let data = try JSONSerialization.data(withJSONObject: registration, options: [.prettyPrinted, .sortedKeys])
        let prepared = lock.appendingPathComponent("registration.json")
        try data.write(to: prepared)
        try fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: prepared.path)
        // Publish complete JSON atomically; link fails if anything owns the target.
        guard link(prepared.path, manifest.path) == 0 else { try fail("Browser registration failed. The new application was rolled back.") }
        return "Installed. Return to LessonShelf in Firefox and choose Connect."
    } catch {
        // Only artifacts created by this invocation are eligible for rollback.
        if installed {
            do { try fm.removeItem(at: app) } catch {
                keepLock = true
                try fail("Installation failed and automatic rollback could not finish. Keep this folder for support: " + lock.path)
            }
        }
        throw error
    }
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
    let app = NSApplication.shared
    app.setActivationPolicy(.regular)
    app.appearance = NSAppearance(named: .darkAqua)
    app.activate(ignoringOtherApps: true)
    let alert = NSAlert()
    alert.messageText = "Install LessonShelf companion"
    alert.informativeText = "Install for your Mac account and connect Firefox. No administrator password is needed. Existing installations are kept."
    alert.addButton(withTitle: "Install"); alert.addButton(withTitle: "Cancel")
    if alert.runModal() == .alertFirstButtonReturn {
        let result = NSAlert()
        do {
            guard let resources = Bundle.main.resourceURL else { try fail("Installer resources are missing.") }
            result.messageText = "LessonShelf companion installed"
            result.informativeText = try install(payload: resources.appendingPathComponent("payload"), userRoot: fm.homeDirectoryForCurrentUser, dryRun: false, staging: false)
        } catch {
            result.alertStyle = .warning
            result.messageText = "Companion was not installed"
            result.informativeText = error.localizedDescription
        }
        result.addButton(withTitle: "OK"); result.runModal()
    }
}
