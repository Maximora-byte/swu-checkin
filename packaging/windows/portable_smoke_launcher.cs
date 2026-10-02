// CI-only, same-user restricted-token launcher. No accounts, passwords, ACLs,
// registry entries, installed software or machine security settings are changed.
// This checks effective non-admin access; it is not a separate standard-user
// account, a sandbox boundary, or a replacement for supported-Windows testing.
// API contracts: https://learn.microsoft.com/windows/win32/api/securitybaseapi/nf-securitybaseapi-createrestrictedtoken
// https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessasuserw
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Principal;
using System.Text;

public sealed class PortableSmokeLauncher : IDisposable
{
    private IntPtr token;
    private IntPtr job;
    private const uint TOKEN_ASSIGN_PRIMARY = 0x0001, TOKEN_DUPLICATE = 0x0002, TOKEN_IMPERSONATE = 0x0004, TOKEN_QUERY = 0x0008;
    private const uint DISABLE_MAX_PRIVILEGE = 0x1, LUA_TOKEN = 0x4;
    private const uint CREATE_SUSPENDED = 0x4, CREATE_UNICODE_ENVIRONMENT = 0x400;
    private const uint SE_GROUP_ENABLED = 0x4, SE_GROUP_USE_FOR_DENY_ONLY = 0x10;

    [StructLayout(LayoutKind.Sequential)]
    private struct SidAndAttributes { public IntPtr Sid; public uint Attributes; }
    [StructLayout(LayoutKind.Sequential)]
    private struct TokenGroups { public uint Count; public SidAndAttributes First; }
    [StructLayout(LayoutKind.Sequential)]
    private struct Luid { public uint Low; public int High; }
    [StructLayout(LayoutKind.Sequential)]
    private struct LuidAndAttributes { public Luid Luid; public uint Attributes; }
    [StructLayout(LayoutKind.Sequential)]
    private struct TokenPrivileges { public uint Count; public LuidAndAttributes First; }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct StartupInfo
    {
        public int cb;
        public string reserved, desktop, title;
        public uint x, y, xSize, ySize, xCountChars, yCountChars, fillAttribute, flags;
        public ushort showWindow, reserved2Size;
        public IntPtr reserved2, stdInput, stdOutput, stdError;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct ProcessInformation { public IntPtr process, thread; public uint processId, threadId; }
    [StructLayout(LayoutKind.Sequential)]
    private struct BasicLimit
    {
        public long processTime, jobTime;
        public uint flags;
        public UIntPtr minimumWorkingSet, maximumWorkingSet;
        public uint activeProcessLimit;
        public UIntPtr affinity;
        public uint priorityClass, schedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct IoCounters { public ulong readOps, writeOps, otherOps, readBytes, writeBytes, otherBytes; }
    [StructLayout(LayoutKind.Sequential)]
    private struct ExtendedLimit
    {
        public BasicLimit basic;
        public IoCounters io;
        public UIntPtr processMemoryLimit, jobMemoryLimit, peakProcessMemory, peakJobMemory;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct Accounting
    {
        public long userTime, kernelTime, periodUserTime, periodKernelTime;
        public uint pageFaults, totalProcesses, activeProcesses, terminatedProcesses;
    }

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool OpenProcessToken(IntPtr process, uint access, out IntPtr token);
    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool CreateRestrictedToken(IntPtr existing, uint flags, uint disableCount,
        [In] SidAndAttributes[] disable, uint deleteCount, IntPtr delete,
        uint restrictCount, IntPtr restrict, out IntPtr result);
    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool ImpersonateLoggedOnUser(IntPtr token);
    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool RevertToSelf();
    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool GetTokenInformation(IntPtr token, int kind, IntPtr buffer, int length, out int needed);
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool LookupPrivilegeValue(string system, string name, out Luid value);
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CreateProcessAsUser(IntPtr token, string application, StringBuilder command,
        IntPtr processAttributes, IntPtr threadAttributes, bool inheritHandles, uint flags,
        IntPtr environment, string directory, ref StartupInfo startup, out ProcessInformation process);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(IntPtr job, int kind, ref ExtendedLimit limit, uint length);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool QueryInformationJobObject(IntPtr job, int kind, out Accounting info, uint length, IntPtr returned);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool TerminateProcess(IntPtr process, uint code);
    [DllImport("kernel32.dll")]
    private static extern bool CloseHandle(IntPtr handle);

    private static void Require(bool result, string operation)
    {
        if (!result) throw new Win32Exception(Marshal.GetLastWin32Error(), operation);
    }

    private static IntPtr ReadToken(IntPtr token, int kind)
    {
        int size;
        GetTokenInformation(token, kind, IntPtr.Zero, 0, out size);
        if (size <= 0) throw new Win32Exception(Marshal.GetLastWin32Error(), "Measure token information");
        IntPtr buffer = Marshal.AllocHGlobal(size);
        try { Require(GetTokenInformation(token, kind, buffer, size, out size), "Read token information"); }
        catch { Marshal.FreeHGlobal(buffer); throw; }
        return buffer;
    }

    private static void AssertRestricted(IntPtr candidate)
    {
        IntPtr groups = ReadToken(candidate, 2); // TokenGroups
        try
        {
            int count = Marshal.ReadInt32(groups);
            int offset = Marshal.OffsetOf<TokenGroups>("First").ToInt32();
            for (int i = 0; i < count; i++)
            {
                var group = Marshal.PtrToStructure<SidAndAttributes>(IntPtr.Add(groups, offset + i * Marshal.SizeOf<SidAndAttributes>()));
                if (new SecurityIdentifier(group.Sid).IsWellKnown(WellKnownSidType.BuiltinAdministratorsSid) &&
                    ((group.Attributes & SE_GROUP_ENABLED) != 0 || (group.Attributes & SE_GROUP_USE_FOR_DENY_ONLY) == 0))
                    throw new InvalidOperationException("Administrators SID is still usable for access grants.");
            }
        }
        finally { Marshal.FreeHGlobal(groups); }
        Luid notify;
        Require(LookupPrivilegeValue(null, "SeChangeNotifyPrivilege", out notify), "Resolve traversal privilege");
        IntPtr privileges = ReadToken(candidate, 3); // TokenPrivileges
        try
        {
            int count = Marshal.ReadInt32(privileges);
            int offset = Marshal.OffsetOf<TokenPrivileges>("First").ToInt32();
            for (int i = 0; i < count; i++)
            {
                var privilege = Marshal.PtrToStructure<LuidAndAttributes>(IntPtr.Add(privileges, offset + i * Marshal.SizeOf<LuidAndAttributes>()));
                // Reject even disabled retained privileges: the child must not
                // be able to re-enable a privilege removed by this launcher.
                if (privilege.Luid.Low != notify.Low || privilege.Luid.High != notify.High)
                    throw new InvalidOperationException("Restricted token retained a non-traversal privilege.");
            }
        }
        finally { Marshal.FreeHGlobal(privileges); }
    }

    public PortableSmokeLauncher()
    {
        if (Environment.GetEnvironmentVariable("OS") != "Windows_NT" ||
            Environment.GetEnvironmentVariable("GITHUB_ACTIONS") != "true" ||
            Environment.GetEnvironmentVariable("RUNNER_ENVIRONMENT") != "github-hosted" ||
            Environment.GetEnvironmentVariable("ImageOS") != "win22")
            throw new InvalidOperationException("Restricted-token smoke requires disposable GitHub-hosted windows-2022.");
        IntPtr original = IntPtr.Zero, adminSid = IntPtr.Zero;
        try
        {
            Require(OpenProcessToken(Process.GetCurrentProcess().Handle, TOKEN_ASSIGN_PRIMARY | TOKEN_DUPLICATE | TOKEN_IMPERSONATE | TOKEN_QUERY,
                out original), "Open own token");
            var admin = new SecurityIdentifier(WellKnownSidType.BuiltinAdministratorsSid, null);
            byte[] sid = new byte[admin.BinaryLength];
            admin.GetBinaryForm(sid, 0);
            adminSid = Marshal.AllocHGlobal(sid.Length);
            Marshal.Copy(sid, 0, adminSid, sid.Length);
            Require(CreateRestrictedToken(original, LUA_TOKEN | DISABLE_MAX_PRIVILEGE, 1,
                new[] { new SidAndAttributes { Sid = adminSid } }, 0, IntPtr.Zero, 0, IntPtr.Zero, out token),
                "Create same-user restricted token (no elevated fallback)");
            AssertRestricted(token);
            job = CreateJobObject(IntPtr.Zero, null);
            if (job == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error(), "Create owned-process job");
            var limits = new ExtendedLimit();
            limits.basic.flags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            Require(SetInformationJobObject(job, 9, ref limits, (uint)Marshal.SizeOf<ExtendedLimit>()), "Contain owned processes");
        }
        catch { Dispose(); throw; }
        finally
        {
            if (original != IntPtr.Zero) CloseHandle(original);
            if (adminSid != IntPtr.Zero) Marshal.FreeHGlobal(adminSid);
        }
    }

    public string DescribeTokenOwner()
    {
        IntPtr userInfo = ReadToken(token, 1); // TokenUser
        IntPtr ownerInfo = ReadToken(token, 4); // TokenOwner
        try
        {
            var user = new SecurityIdentifier(Marshal.ReadIntPtr(userInfo));
            var owner = new SecurityIdentifier(Marshal.ReadIntPtr(ownerInfo));
            return "owner_is_user=" + owner.Equals(user) + "; owner_is_administrators=" +
                owner.IsWellKnown(WellKnownSidType.BuiltinAdministratorsSid);
        }
        finally { Marshal.FreeHGlobal(userInfo); Marshal.FreeHGlobal(ownerInfo); }
    }

    public string ProbeWritableDirectory(string directory)
    {
        // Check this harness's synthetic directories with the exact launch
        // token. No ACL or token changes, credentials, or profile loading.
        string path = Path.Combine(directory, "portable-write-probe-" + Guid.NewGuid().ToString("N") + ".tmp");
        Require(ImpersonateLoggedOnUser(token), "Impersonate own restricted token for storage probe");
        try
        {
            File.WriteAllText(path, "synthetic-offline-probe");
            if (File.ReadAllText(path) != "synthetic-offline-probe") return "READ_MISMATCH";
            File.Delete(path);
            return "WRITABLE";
        }
        catch (UnauthorizedAccessException) { return "ACCESS_DENIED"; }
        catch (IOException error) { return "IO_ERROR_" + error.HResult.ToString("X8"); }
        finally
        {
            // Never leave the PowerShell verification thread impersonating.
            if (!RevertToSelf()) Environment.FailFast("Could not revert restricted-token storage probe.");
            if (File.Exists(path)) File.Delete(path);
        }
    }

    public Process Start(string executable, string argument, string directory, IDictionary<string, string> environment)
    {
        // This deliberately narrow interface cannot run arbitrary CLI modes.
        if (argument != "" && argument != "--self-test") throw new ArgumentException("Only GUI or offline self-test permitted.");
        return StartCommand(executable, argument, directory, environment);
    }

    public Process StartDiagnostic(string python, string script, string report, string directory,
        IDictionary<string, string> environment)
    {
        // The source-only diagnostic is never an acceptance substitute and may
        // run only this checked-in, synthetic offline helper after a failure.
        if (!Path.GetFileName(python).Equals("python.exe", StringComparison.OrdinalIgnoreCase) ||
            !Path.GetFileName(script).Equals("portable_diagnostic.py", StringComparison.Ordinal) ||
            script.IndexOf('"') >= 0 || report.IndexOf('"') >= 0)
            throw new ArgumentException("Unexpected diagnostic target.");
        return StartCommand(python, "-I -B \"" + script + "\" \"" + report + "\"", directory, environment);
    }

    private Process StartCommand(string executable, string arguments, string directory, IDictionary<string, string> environment)
    {
        if (executable.IndexOf('"') >= 0) throw new ArgumentException("Unexpected executable path.");
        var sorted = new SortedDictionary<string, string>(environment, StringComparer.OrdinalIgnoreCase);
        var block = new StringBuilder();
        foreach (var item in sorted) block.Append(item.Key).Append('=').Append(item.Value).Append('\0');
        block.Append('\0');
        IntPtr environmentBlock = Marshal.StringToHGlobalUni(block.ToString());
        ProcessInformation info = new ProcessInformation();
        Process process = null;
        bool resumed = false;
        try
        {
            // NULL inherits the runner's existing desktop/window station;
            // never assume the hosted runner uses winsta0\default or edit its ACL.
            var startup = new StartupInfo { cb = Marshal.SizeOf<StartupInfo>() };
            var command = new StringBuilder("\"" + executable + "\"" + (arguments == "" ? "" : " " + arguments));
            Require(CreateProcessAsUser(token, executable, command, IntPtr.Zero, IntPtr.Zero, false,
                CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT, environmentBlock, directory, ref startup, out info),
                "Start restricted process (no elevated fallback)");
            Require(AssignProcessToJobObject(job, info.process), "Track all descendants in owned job");
            IntPtr actualToken;
            Require(OpenProcessToken(info.process, TOKEN_QUERY, out actualToken), "Inspect actual child token");
            try { AssertRestricted(actualToken); }
            finally { CloseHandle(actualToken); }
            process = Process.GetProcessById((int)info.processId);
            // Cache a real handle while suspended so exit status remains
            // available even when the offline self-test exits very quickly.
            IntPtr cached = process.Handle;
            if (ResumeThread(info.thread) == uint.MaxValue)
                throw new Win32Exception(Marshal.GetLastWin32Error(), "Resume verified restricted process");
            resumed = true;
            return process;
        }
        finally
        {
            if (!resumed && info.process != IntPtr.Zero) TerminateProcess(info.process, 1);
            if (!resumed && process != null) process.Dispose();
            if (info.thread != IntPtr.Zero) CloseHandle(info.thread);
            if (info.process != IntPtr.Zero) CloseHandle(info.process);
            Marshal.FreeHGlobal(environmentBlock);
        }
    }

    public uint ActiveProcesses
    {
        get
        {
            Accounting accounting;
            Require(QueryInformationJobObject(job, 1, out accounting, (uint)Marshal.SizeOf<Accounting>(), IntPtr.Zero),
                "Count owned processes and descendants");
            return accounting.activeProcesses;
        }
    }

    public void Dispose()
    {
        // Closing this private job terminates only processes we launched and
        // their descendants, including children of already-exited parents.
        if (job != IntPtr.Zero) { CloseHandle(job); job = IntPtr.Zero; }
        if (token != IntPtr.Zero) { CloseHandle(token); token = IntPtr.Zero; }
    }
}
