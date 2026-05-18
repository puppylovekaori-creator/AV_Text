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

        using var mutex = new Mutex(true, MutexName, out var createdNew);
        if (!createdNew)
        {
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

        Application.Run(new MainForm());
    }
}
