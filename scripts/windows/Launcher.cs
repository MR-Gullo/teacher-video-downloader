using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Web.Script.Serialization;

class Launcher {
    static int Main() {
        try {
            string app = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
            string state = Directory.GetParent(app).FullName;
            var record = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(Path.Combine(app, ".installation.json")));
            var start = new ProcessStartInfo(Path.Combine(app, "runtime", "python.exe"), "-B -I \"" + Path.Combine(app, "installer", "run_host.py") + "\"");
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.EnvironmentVariables["PATH"] = Path.Combine(app, "tools") + ";" + Environment.GetFolderPath(Environment.SpecialFolder.System) + ";" + Environment.GetEnvironmentVariable("SystemRoot");
            start.EnvironmentVariables.Remove("PYTHONPATH");
            start.EnvironmentVariables.Remove("PYTHONHOME");
            start.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";
            start.EnvironmentVariables["PYTHONDONTWRITEBYTECODE"] = "1";
            start.EnvironmentVariables["TVD_STATE_DIR"] = state;
            start.EnvironmentVariables["YTDL_OUTPUT_DIR"] = (string)record["outputDir"];
            using (var child = Process.Start(start)) { child.WaitForExit(); return child.ExitCode; }
        } catch { Console.Error.WriteLine("LessonShelf companion could not start. Run the installer again."); return 1; }
    }
}
