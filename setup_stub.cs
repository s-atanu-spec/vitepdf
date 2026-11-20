// VitePDF-Setup.exe: the installer you share as one file.
//
// It carries a ZIP inside itself (Python, the libraries, VitePDF and
// VitePDF.exe). All it does: unpack that ZIP to a temporary folder, start the
// VitePDF installer window from it, wait, and remove the temporary folder.
// build-setup.bat makes it with the C# compiler that is part of Windows.
//
// Created by Atanu Sarkar. Made with Claude.

using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("VitePDF Setup")]
[assembly: AssemblyDescription("Installs VitePDF: right-click image and PDF tools")]
[assembly: AssemblyProduct("VitePDF")]
[assembly: AssemblyCompany("Atanu Sarkar")]
[assembly: AssemblyCopyright("Created by Atanu Sarkar. Made with Claude.")]
[assembly: AssemblyVersion("1.4.0.0")]
[assembly: AssemblyFileVersion("1.4.0.0")]

internal static class Program
{
    private static string Quote(string arg)
    {
        // The paths used here never contain a quote; a trailing backslash is doubled.
        if (arg.EndsWith("\\"))
        {
            arg = arg + "\\";
        }
        return "\"" + arg + "\"";
    }

    [STAThread]
    private static int Main()
    {
        Application.EnableVisualStyles();
        string temp = Path.Combine(Path.GetTempPath(), "VitePDF-Setup-" + Guid.NewGuid().ToString("N"));
        int code = 1;

        Form splash = new Form();
        splash.Text = "VitePDF Setup";
        splash.FormBorderStyle = FormBorderStyle.FixedDialog;
        splash.StartPosition = FormStartPosition.CenterScreen;
        splash.ClientSize = new Size(360, 90);
        splash.ControlBox = false;
        splash.BackColor = Color.FromArgb(243, 243, 243);
        Label label = new Label();
        label.Text = "Preparing VitePDF Setup. This takes a few seconds.";
        label.Font = new Font("Segoe UI", 10f);
        label.Dock = DockStyle.Fill;
        label.TextAlign = ContentAlignment.MiddleCenter;
        splash.Controls.Add(label);

        try
        {
            splash.Show();
            Application.DoEvents();
            Directory.CreateDirectory(temp);
            string prefix = temp + Path.DirectorySeparatorChar;

            using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
            {
                if (stream == null)
                {
                    throw new IOException("This Setup file is incomplete.");
                }
                using (ZipArchive zip = new ZipArchive(stream, ZipArchiveMode.Read))
                {
                    int count = 0;
                    foreach (ZipArchiveEntry entry in zip.Entries)
                    {
                        string dest = Path.GetFullPath(Path.Combine(temp, entry.FullName));
                        // Never write outside the temporary folder.
                        if (!dest.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                        {
                            throw new IOException("This Setup file is damaged.");
                        }
                        if (entry.FullName.EndsWith("/") || entry.FullName.EndsWith("\\"))
                        {
                            Directory.CreateDirectory(dest);
                            continue;
                        }
                        Directory.CreateDirectory(Path.GetDirectoryName(dest));
                        using (Stream src = entry.Open())
                        using (FileStream dst = File.Create(dest))
                        {
                            src.CopyTo(dst);
                        }
                        count++;
                        if (count % 50 == 0)
                        {
                            Application.DoEvents();
                        }
                    }
                }
            }

            string python = Path.Combine(Path.Combine(temp, "runtime"), "pythonw.exe");
            string script = Path.Combine(Path.Combine(temp, "app"), "vitepdf.py");
            ProcessStartInfo psi = new ProcessStartInfo(python,
                "-I " + Quote(script) + " --installer " + Quote(temp));
            psi.UseShellExecute = false;
            psi.WorkingDirectory = temp;
            splash.Hide();
            using (Process p = Process.Start(psi))
            {
                p.WaitForExit();
                code = p.ExitCode;
            }
        }
        catch (Exception e)
        {
            splash.Hide();
            MessageBox.Show("VitePDF Setup could not start.\n\n" + e.Message, "VitePDF Setup",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }
        finally
        {
            splash.Dispose();
            try
            {
                Directory.Delete(temp, true);
            }
            catch (Exception)
            {
            }
        }
        return code;
    }
}
