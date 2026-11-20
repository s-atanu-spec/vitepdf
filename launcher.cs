// VitePDF.exe: a tiny starter with the VitePDF logo.
//
// It is compiled with the C# compiler that is part of Windows: by install.bat
// on your own computer, or by build-setup.bat when Setup.exe is made.
// All it does is start  pythonw.exe -I app\vitepdf.py <arguments>  from the
// folder it sits in (runtime\ after Setup.exe, venv\Scripts\ after install.bat).
// Started without arguments it shows "About".
//
// Created by Atanu Sarkar. Made with Claude.

using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;

[assembly: AssemblyTitle("VitePDF")]
[assembly: AssemblyDescription("Right-click image and PDF tools")]
[assembly: AssemblyProduct("VitePDF")]
[assembly: AssemblyCompany("Atanu Sarkar")]
[assembly: AssemblyCopyright("Created by Atanu Sarkar. Made with Claude.")]
[assembly: AssemblyVersion("1.4.0.0")]
[assembly: AssemblyFileVersion("1.4.0.0")]

internal static class Program
{
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBoxW(IntPtr hWnd, string text, string caption, uint type);

    // Quote one argument the way Windows programs expect it, so a file name
    // can never be read as more than one argument.
    private static string Quote(string arg)
    {
        if (arg.Length > 0 && arg.IndexOfAny(new char[] { ' ', '\t', '"' }) < 0)
        {
            return arg;
        }
        StringBuilder sb = new StringBuilder();
        sb.Append('"');
        int slashes = 0;
        foreach (char c in arg)
        {
            if (c == '\\')
            {
                slashes++;
            }
            else if (c == '"')
            {
                sb.Append('\\', slashes * 2 + 1);
                sb.Append('"');
                slashes = 0;
            }
            else
            {
                sb.Append('\\', slashes);
                sb.Append(c);
                slashes = 0;
            }
        }
        sb.Append('\\', slashes * 2);
        sb.Append('"');
        return sb.ToString();
    }

    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            string root = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
            string python = Path.Combine(Path.Combine(root, "runtime"), "pythonw.exe");
            if (!File.Exists(python))
            {
                python = Path.Combine(Path.Combine(Path.Combine(root, "venv"), "Scripts"), "pythonw.exe");
            }
            string script = Path.Combine(Path.Combine(root, "app"), "vitepdf.py");
            if (!File.Exists(python) || !File.Exists(script))
            {
                MessageBoxW(IntPtr.Zero, "VitePDF is not completely installed. Run the installer again.", "VitePDF", 0x30);
                return 1;
            }

            StringBuilder cmd = new StringBuilder();
            cmd.Append("-I ");
            cmd.Append(Quote(script));
            if (args.Length == 0)
            {
                cmd.Append(" --about");
            }
            foreach (string a in args)
            {
                cmd.Append(' ');
                cmd.Append(Quote(a));
            }

            ProcessStartInfo psi = new ProcessStartInfo(python, cmd.ToString());
            psi.UseShellExecute = false;
            psi.WorkingDirectory = root;
            Process.Start(psi);
            return 0;
        }
        catch (Exception e)
        {
            MessageBoxW(IntPtr.Zero, "VitePDF could not start.\n\n" + e.Message, "VitePDF", 0x30);
            return 1;
        }
    }
}
