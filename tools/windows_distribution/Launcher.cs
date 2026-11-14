using System;
using System.Diagnostics;
using System.IO;
using System.Text.RegularExpressions;
using System.Windows.Forms;

internal static class Launcher {
    [STAThread] static int Main() {
        try {
            string location = AppDomain.CurrentDomain.BaseDirectory;
            string root = Directory.GetParent(location.TrimEnd(Path.DirectorySeparatorChar)).Parent.FullName;
            string version = File.ReadAllText(Path.Combine(root,"current.txt"));
            if (!Regex.IsMatch(version, @"\A[0-9a-f]{20}\z")) throw new InvalidDataException("Invalid installation.");
            string selected = Path.Combine(root,"versions",version);
            Process.Start(new ProcessStartInfo(Path.Combine(selected,"pythonw.exe"),"-I -B \"" +
                Path.Combine(selected,"launch.py") + "\"") {WorkingDirectory=selected,UseShellExecute=false});
            return 0;
        } catch (Exception error) {
            MessageBox.Show(error.Message,"RESEARCH-Y",MessageBoxButtons.OK,MessageBoxIcon.Error);
            return 1;
        }
    }
}
