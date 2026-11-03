using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

class Launcher {
    static async Task Pump(Stream source, Stream destination, bool closeDestination) {
        try {
            byte[] buffer = new byte[8192];
            int count;
            while ((count = await source.ReadAsync(buffer, 0, buffer.Length).ConfigureAwait(false)) != 0) {
                await destination.WriteAsync(buffer, 0, count).ConfigureAwait(false);
                // Native messaging is interactive: never wait for EOF to flush a short frame.
                await destination.FlushAsync().ConfigureAwait(false);
            }
        } finally {
            if (closeDestination) destination.Close();
        }
    }
    static int Main() {
        try {
            string app = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
            string state = Directory.GetParent(app).FullName;
            var record = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(Path.Combine(app, ".installation.json")));
            var start = new ProcessStartInfo(Path.Combine(app, "runtime", "python.exe"), "-B -I \"" + Path.Combine(app, "installer", "run_host.py") + "\"");
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.RedirectStandardInput = true;
            start.RedirectStandardOutput = true;
            start.RedirectStandardError = true;
            start.EnvironmentVariables["PATH"] = Path.Combine(app, "tools") + ";" + Environment.GetFolderPath(Environment.SpecialFolder.System) + ";" + Environment.GetEnvironmentVariable("SystemRoot");
            start.EnvironmentVariables.Remove("PYTHONPATH");
            start.EnvironmentVariables.Remove("PYTHONHOME");
            start.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
            start.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
            start.EnvironmentVariables["TVD_STATE_DIR"] = state;
            start.EnvironmentVariables["YTDL_OUTPUT_DIR"] = (string)record["outputDir"];
            using (var child = Process.Start(start)) {
                var input = Pump(Console.OpenStandardInput(), child.StandardInput.BaseStream, true);
                var output = Pump(child.StandardOutput.BaseStream, Console.OpenStandardOutput(), false);
                var error = Pump(child.StandardError.BaseStream, Console.OpenStandardError(), false);
                child.WaitForExit();
                Task.WaitAll(output, error);
                // The browser may keep its input pipe open after a child exits. Do not wait on it.
                if (input.IsFaulted) throw input.Exception.GetBaseException();
                return child.ExitCode;
            }
        } catch (Exception error) {
            Console.Error.WriteLine("LessonShelf companion could not start: " + error.Message);
            return 1;
        }
    }
}
