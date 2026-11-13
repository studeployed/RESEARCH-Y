using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Threading;
using System.Windows.Forms;

// The build embeds its own verified application image. No external command,
// downloaded script, project or user-provided archive is executed by Setup.
internal static class Setup {
    static string Install(string root) {
        string image = BuildInfo.Image;
        string releases = Path.Combine(root, "versions");
        string directoryId = image.Substring(0, 20);
        string destination = Path.Combine(releases, directoryId);
        Directory.CreateDirectory(releases);
        string staging = Path.Combine(releases, ".s-" + Guid.NewGuid().ToString("N").Substring(0, 12));
        Directory.CreateDirectory(staging);
        try {
            using (Stream payload = Assembly.GetExecutingAssembly().GetManifestResourceStream("application.zip")) {
                using (var hash = SHA256.Create()) {
                    string actual = BitConverter.ToString(hash.ComputeHash(payload)).Replace("-", "").ToLowerInvariant();
                    if (actual != image) throw new InvalidDataException("Application payload checksum mismatch.");
                }
                payload.Position = 0;
                using (var archive = new ZipArchive(payload, ZipArchiveMode.Read)) {
                    string prefix = Path.GetFullPath(staging) + Path.DirectorySeparatorChar;
                    foreach (ZipArchiveEntry entry in archive.Entries) {
                        string path = Path.GetFullPath(Path.Combine(staging, entry.FullName.Replace('/', Path.DirectorySeparatorChar)));
                        if (!path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase) || entry.Name.Length == 0)
                            throw new InvalidDataException("Invalid application image.");
                        // The per-user install can live below a lengthy Windows profile.
                        string ioPath = @"\\?\" + path;
                        Directory.CreateDirectory(Path.GetDirectoryName(ioPath));
                        using (Stream input = entry.Open())
                        using (FileStream output = new FileStream(ioPath, FileMode.CreateNew, FileAccess.Write))
                            input.CopyTo(output);
                    }
                }
            }
            if (!Directory.Exists(destination)) Directory.Move(staging, destination);
            else {
                // Match every delivered file before reusing an installed version.
                foreach (string installed in Directory.GetFiles(destination, "*", SearchOption.AllDirectories)) {
                    string relative = installed.Substring(destination.Length + 1);
                    if (File.Exists(Path.Combine(staging, relative))) continue;
                    if (Path.GetFileName(Path.GetDirectoryName(installed)) == "__pycache__" &&
                        Path.GetExtension(installed) == ".pyc") continue;
                    throw new InvalidDataException("Installed application has unexpected files.");
                }
                foreach (string candidate in Directory.GetFiles(staging, "*", SearchOption.AllDirectories)) {
                    string installed = Path.Combine(destination, candidate.Substring(staging.Length + 1));
                    using (var hash = SHA256.Create())
                    using (Stream a = File.OpenRead(candidate))
                    using (Stream b = File.OpenRead(installed)) {
                        if (Convert.ToBase64String(hash.ComputeHash(a)) != Convert.ToBase64String(hash.ComputeHash(b)))
                            throw new InvalidDataException("Installed image differs from this installer.");
                    }
                }
            }
            string pointer = Path.Combine(root, "current.txt");
            string temporary = Path.Combine(root, ".current-" + Guid.NewGuid().ToString("N"));
            File.WriteAllText(temporary, directoryId);
            if (File.Exists(pointer)) {
                if (File.ReadAllText(pointer) != directoryId) File.Replace(temporary, pointer, Path.Combine(root, "previous.txt"));
                else File.Delete(temporary);
            } else File.Move(temporary, pointer);
            return destination;
        } finally {
            if (Directory.Exists(staging)) Directory.Delete(staging, true);
        }
    }

    static void Shortcut(string root, string installed) {
        string menu = Environment.GetFolderPath(Environment.SpecialFolder.Programs);
        Type shellType = Type.GetTypeFromProgID("WScript.Shell", true);
        dynamic shell = Activator.CreateInstance(shellType);
        dynamic shortcut = shell.CreateShortcut(Path.Combine(menu, "RESEARCH-Y.lnk"));
        shortcut.TargetPath = Path.Combine(installed, "RESEARCH-Y.exe");
        shortcut.WorkingDirectory = root;
        shortcut.Description = "Open RESEARCH-Y";
        shortcut.Save();
    }

    [STAThread] static int Main(string[] args) {
        try {
            AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling", false);
            AppContext.SetSwitch("Switch.System.IO.BlockLongPaths", false);
            bool quiet = args.Length == 2 && args[0] == "--test-install-root";
            string root = quiet ? Path.GetFullPath(args[1]) : Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "RESEARCH-Y");
            if (!quiet && args.Length != 0) return 2;
            if (!quiet && MessageBox.Show("Install or update RESEARCH-Y for your Windows account?",
                    "RESEARCH-Y Setup", MessageBoxButtons.OKCancel) != DialogResult.OK) return 0;
            using (var mutex = new Mutex(false, "Local\\RESEARCH-Y-Desktop-Setup")) {
                try { if (!mutex.WaitOne(0)) throw new IOException("Another installation is running."); }
                catch (AbandonedMutexException) { }
                try {
                    string target = Install(root);
                    if (!quiet) {
                        Shortcut(root, target);
                        if (MessageBox.Show("Installation complete. Open RESEARCH-Y?", "RESEARCH-Y Setup",
                                MessageBoxButtons.YesNo) == DialogResult.Yes)
                            Process.Start(Path.Combine(target, "RESEARCH-Y.exe"));
                    }
                } finally { mutex.ReleaseMutex(); }
            }
            return 0;
        } catch (Exception error) {
            if (args.Length == 0) MessageBox.Show(error.Message, "RESEARCH-Y Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
            else Console.Error.WriteLine(error.GetType().Name + ": " + error.Message);
            return 1;
        }
    }
}
