// Native messaging entry point inside the sealed installed companion app.
import Foundation
import Darwin

do {
    let executable = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
    let bundle = executable.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
    let app = bundle.deletingLastPathComponent()
    let state = app.deletingLastPathComponent()
    let payload = bundle.appendingPathComponent("Contents/Resources/payload")
    let record = try JSONSerialization.jsonObject(with: Data(contentsOf: app.appendingPathComponent(".installation.json"))) as? [String: Any]
    guard let output = record?["outputDir"] as? String else { throw NSError(domain: "LessonShelf", code: 1, userInfo: [NSLocalizedDescriptionKey: "The installation record is missing."]) }
    umask(0o077)
    setenv("PATH", payload.appendingPathComponent("tools").path + ":/usr/bin:/bin", 1)
    setenv("PYTHONNOUSERSITE", "1", 1)
    setenv("PYTHONDONTWRITEBYTECODE", "1", 1)
    unsetenv("PYTHONHOME"); unsetenv("PYTHONPATH")
    setenv("TVD_STATE_DIR", state.path, 1)
    setenv("YTDL_OUTPUT_DIR", output, 1)
    let python = payload.appendingPathComponent("runtime/bin/python3").path
    let arguments = [python, "-B", "-I", payload.appendingPathComponent("installer/run_host.py").path] + CommandLine.arguments.dropFirst()
    var pointers = arguments.map { strdup($0) } + [nil]
    execv(python, &pointers)
    for pointer in pointers { free(pointer) }
    throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno))
} catch {
    fputs("LessonShelf companion could not start: \(error.localizedDescription)\n", stderr)
    exit(1)
}
