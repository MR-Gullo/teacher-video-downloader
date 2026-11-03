using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Threading.Tasks;
using System.Windows.Forms;

class Installer {
    const string PayloadHash = "PAYLOAD_SHA256_PLACEHOLDER";
    static bool Supported() {
        string arch = Environment.GetEnvironmentVariable("PROCESSOR_ARCHITEW6432") ?? Environment.GetEnvironmentVariable("PROCESSOR_ARCHITECTURE") ?? "";
        return Environment.Is64BitOperatingSystem && arch.Equals("AMD64", StringComparison.OrdinalIgnoreCase);
    }
    static string Hash(string file) { using (var sha = SHA256.Create()) using (var stream = File.OpenRead(file)) return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant(); }
    static string Quote(string value) {
        if (value.Contains("\"") || value.Contains("\r") || value.Contains("\n")) throw new Exception("Invalid installation path.");
        return "\"" + value.TrimEnd('\\') + "\"";
    }
    static string Run(string[] args) {
        if (!Supported()) throw new Exception("This installer supports Windows x64. Windows ARM64 and 32-bit Windows are not supported.");
        string directory = Path.Combine(Path.GetTempPath(), "LessonShelf-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try {
            string archive = Path.Combine(directory, "payload.zip");
            using (var input = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip")) using (var output = File.Create(archive)) input.CopyTo(output);
            if (Hash(archive) != PayloadHash) throw new Exception("Installer integrity check failed. Download it again.");
            string payload = Path.Combine(directory, "payload");
            // ZIP paths originate in a reviewed embedded resource, but still reject traversal.
            using (var archiveStream = File.OpenRead(archive)) using (var zip = new ZipArchive(archiveStream, ZipArchiveMode.Read)) {
                foreach (var entry in zip.Entries) {
                    string destination = Path.GetFullPath(Path.Combine(payload, entry.FullName));
                    if (!destination.StartsWith(payload + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new Exception("Invalid payload path.");
                    if (entry.FullName.EndsWith("/")) { Directory.CreateDirectory(destination); continue; }
                    Directory.CreateDirectory(Path.GetDirectoryName(destination));
                    using (var input = entry.Open()) using (var output = File.Create(destination)) input.CopyTo(output);
                }
            }
            string command = "-B -I " + Quote(Path.Combine(payload, "installer", "install_payload.py")) + " --payload " + Quote(payload);
            if (args.Length == 1 && args[0] == "--install") command += " --install";
            else if (args.Length > 0) {
                if (args.Length != 2 && args.Length != 3 || args[0] != "--stage-root" || args.Length == 3 && args[2] != "--dry-run") throw new Exception("Use --stage-root DIRECTORY [--dry-run] for isolated tests.");
                command += " --stage-root " + Quote(args[1]);
                if (args.Length == 3) command += " --dry-run";
            } else command += " --install";
            var start = new ProcessStartInfo(Path.Combine(payload, "runtime", "python.exe"), command);
            start.UseShellExecute = false; start.CreateNoWindow = true;
            start.RedirectStandardOutput = true; start.RedirectStandardError = true;
            using (var child = Process.Start(start)) {
                var stdout = child.StandardOutput.ReadToEndAsync();
                var stderr = child.StandardError.ReadToEndAsync();
                child.WaitForExit();
                if (child.ExitCode != 0) throw new Exception(stderr.Result.Trim());
                return stdout.Result.Trim();
            }
        } finally {
            // Delete only this invocation's extraction directory. Installed data is elsewhere.
            try { Directory.Delete(directory, true); } catch { }
        }
    }
    [STAThread]
    static int Main(string[] args) {
        if (args.Length > 0) {
            try { Console.WriteLine(Run(args)); return 0; } catch (Exception error) { Console.Error.WriteLine(error.Message); return 1; }
        }
        Application.EnableVisualStyles();
        var window = new Form { Text = "Install LessonShelf companion", ClientSize = new Size(520, 260), StartPosition = FormStartPosition.CenterScreen, BackColor = Color.FromArgb(37,36,34), ForeColor = Color.FromArgb(255,252,242), FormBorderStyle = FormBorderStyle.FixedDialog, MaximizeBox = false, Font = new Font("Segoe UI", 11) };
        var text = new Label { Text = "Install the Firefox companion for your Windows account. All media tools are included. Your queue and saved videos are kept.", Location = new Point(28,28), Size = new Size(464,90) };
        var status = new Label { Text = "Ready to install. No administrator password is needed.", Location = new Point(28,130), Size = new Size(464,65) };
        var button = new Button { Text = "Install", Location = new Point(352,202), Size = new Size(140,40), BackColor = Color.FromArgb(235,94,40), ForeColor = Color.White, FlatStyle = FlatStyle.Flat, UseVisualStyleBackColor = false };
        bool running = false;
        window.Controls.Add(text); window.Controls.Add(status); window.Controls.Add(button);
        window.AcceptButton = button;
        window.FormClosing += (sender, e) => { if (running) e.Cancel = true; };
        button.Click += async (sender, e) => {
            if (button.Text == "Close") { window.Close(); return; }
            running = true; button.Enabled = false; status.Text = "Checking and installing the bundled tools...";
            try { await Task.Run(() => Run(new string[0])); status.Text = "Installed. Return to LessonShelf in Firefox and choose Connect."; button.Text = "Close"; }
            catch (Exception error) { status.Text = error.Message; button.Text = "Try again"; }
            finally { running = false; button.Enabled = true; }
        };
        Application.Run(window);
        return 0;
    }
}
