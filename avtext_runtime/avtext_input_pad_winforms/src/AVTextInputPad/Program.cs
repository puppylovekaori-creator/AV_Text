using System.Threading;
using System.Text;

namespace AVTextInputPad;

internal static class Program
{
    private const string MutexName = @"Local\AVTextInputPadWinForms";

    [STAThread]
    private static void Main()
    {
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
        MainForm.WriteEmergencyLog($"process start pid={Environment.ProcessId}");

        using var mutex = new Mutex(true, MutexName, out var createdNew);
        if (!createdNew)
        {
            MainForm.WriteEmergencyLog("process reused existing instance");
            NativeWindowHelper.FocusFirstWindowContaining(MainForm.WindowTitle);
            return;
        }

        ApplicationConfiguration.Initialize();
        Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
        Application.ThreadException += (_, args) =>
        {
            MainForm.WriteEmergencyLog($"ui exception: {args.Exception}");
        };
        AppDomain.CurrentDomain.UnhandledException += (_, args) =>
        {
            MainForm.WriteEmergencyLog($"fatal exception: {args.ExceptionObject}");
        };
        Application.ApplicationExit += (_, _) =>
        {
            MainForm.WriteEmergencyLog($"application exit pid={Environment.ProcessId}");
        };

        try
        {
            Application.Run(new MainForm());
        }
        finally
        {
            MainForm.WriteEmergencyLog($"process end pid={Environment.ProcessId}");
        }
    }
}
