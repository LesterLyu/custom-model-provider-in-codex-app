// Compile with the Windows .NET Framework compiler. No third-party binary is bundled.
using System;
using System.Diagnostics;
using System.IO;
using System.Threading.Tasks;

class CodexProviderLauncher {
    static void Pump(Stream source, Stream target) {
        byte[] buffer = new byte[65536];
        int count;
        while ((count = source.Read(buffer, 0, buffer.Length)) > 0) {
            target.Write(buffer, 0, count);
            target.Flush();
        }
    }

    static string Quote(string value) {
        // Windows CommandLineToArgvW quoting, including trailing backslashes.
        var output = new System.Text.StringBuilder("\"");
        int slashes = 0;
        foreach (char ch in value) {
            if (ch == '\\') { slashes++; continue; }
            if (ch == '"') { output.Append('\\', slashes * 2 + 1); output.Append(ch); }
            else { output.Append('\\', slashes); output.Append(ch); }
            slashes = 0;
        }
        output.Append('\\', slashes * 2);
        output.Append('"');
        return output.ToString();
    }

    static int Main(string[] args) {
        try {
            // Framework's Process.StandardInput uses Console.InputEncoding and may
            // otherwise prepend a UTF-8 BOM, which isn't valid before JSONL JSON.
            Console.InputEncoding = new System.Text.UTF8Encoding(false);
            Console.OutputEncoding = new System.Text.UTF8Encoding(false);
            string root = AppDomain.CurrentDomain.BaseDirectory;
            string python = Path.Combine(root, "venv", "Scripts", "python.exe");
            var arguments = "-u " + Quote(Path.Combine(root, "stdio_router.py")) + " --settings " +
                            Quote(Path.Combine(root, "windows.json")) + " --";
            foreach (string arg in args) arguments += " " + Quote(arg);
            var start = new ProcessStartInfo(python, arguments) {
                UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardInput = true, RedirectStandardOutput = true,
                RedirectStandardError = true
            };
            using (var process = Process.Start(start)) {
                Task.Run(() => {
                    try { Pump(Console.OpenStandardInput(), process.StandardInput.BaseStream); }
                    catch (IOException) { }
                    finally { try { process.StandardInput.Close(); } catch (IOException) { } }
                });
                Task output = Task.Run(() => Pump(process.StandardOutput.BaseStream, Console.OpenStandardOutput()));
                Task error = Task.Run(() => Pump(process.StandardError.BaseStream, Console.OpenStandardError()));
                process.WaitForExit();
                Task.WaitAll(output, error);
                return process.ExitCode;
            }
        } catch (Exception error) {
            Console.Error.WriteLine("Codex provider launcher failed: " + error.Message);
            return 1;
        }
    }
}
