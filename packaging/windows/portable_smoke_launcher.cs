// CI-only, same-user restricted-token launcher. No accounts, passwords,
// filesystem/existing-object ACLs, registry entries or machine settings change.
// Only the newly-created restricted token's default DACL is normalized below.
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
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;

public sealed class PortableSmokeLauncher : IDisposable
{
    private IntPtr token;
    private IntPtr job;
    public string DefaultDaclBefore { get; private set; }
    private const uint TOKEN_ADJUST_DEFAULT = 0x0080;
    private const uint TOKEN_ASSIGN_PRIMARY = 0x0001, TOKEN_DUPLICATE = 0x0002, TOKEN_IMPERSONATE = 0x0004, TOKEN_QUERY = 0x0008;
    private const uint DISABLE_MAX_PRIVILEGE = 0x1, LUA_TOKEN = 0x4;
    private const uint CREATE_SUSPENDED = 0x4, CREATE_UNICODE_ENVIRONMENT = 0x400;
    private const uint SE_GROUP_ENABLED = 0x4, SE_GROUP_USE_FOR_DENY_ONLY = 0x10;

    [StructLayout(LayoutKind.Sequential)]
    private struct SidAndAttributes { public IntPtr Sid; public uint Attributes; }
    [StructLayout(LayoutKind.Sequential)]
    private struct TokenDefaultDacl { public IntPtr acl; }
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
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct StartupInfoEx { public StartupInfo startup; public IntPtr attributes; }
    [StructLayout(LayoutKind.Sequential)]
    private struct SecurityAttributes
    {
        public int length;
        public IntPtr descriptor;
        [MarshalAs(UnmanagedType.Bool)] public bool inherit;
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
    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool SetTokenInformation(IntPtr token, int kind, ref TokenDefaultDacl info, int size);
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool LookupPrivilegeValue(string system, string name, out Luid value);
    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CreateProcessAsUser(IntPtr token, string application, StringBuilder command,
        IntPtr processAttributes, IntPtr threadAttributes, bool inheritHandles, uint flags,
        IntPtr environment, string directory, ref StartupInfoEx startup, out ProcessInformation process);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateFile(string name, uint access, uint share,
        ref SecurityAttributes security, uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool InitializeProcThreadAttributeList(IntPtr attributes, int count, uint flags, ref UIntPtr size);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool UpdateProcThreadAttribute(IntPtr attributes, uint flags, IntPtr kind,
        IntPtr value, UIntPtr size, IntPtr previous, IntPtr returned);
    [DllImport("kernel32.dll")]
    private static extern void DeleteProcThreadAttributeList(IntPtr attributes);
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
            Require(OpenProcessToken(Process.GetCurrentProcess().Handle, TOKEN_ASSIGN_PRIMARY | TOKEN_DUPLICATE | TOKEN_IMPERSONATE | TOKEN_QUERY | TOKEN_ADJUST_DEFAULT,
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
            DefaultDaclBefore = DescribeTokenDefaultDacl();
            NormalizeRestrictedDefaultDacl();
            AssertRestricted(token); // Default-object access must not restore privileges/groups.
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

    private static RawAcl ReadDefaultDacl(IntPtr candidate)
    {
        IntPtr info = ReadToken(candidate, 6); // TokenDefaultDacl
        try
        {
            IntPtr acl = Marshal.ReadIntPtr(info);
            if (acl == IntPtr.Zero) return null;
            int length = unchecked((ushort)Marshal.ReadInt16(acl, 2)); // ACL.AclSize
            byte[] data = new byte[length];
            Marshal.Copy(acl, data, 0, length);
            return new RawAcl(data, 0);
        }
        finally { Marshal.FreeHGlobal(info); }
    }

    public string DescribeTokenDefaultDacl()
    {
        IntPtr info = ReadToken(token, 1); // TokenUser; never emit its SID.
        try
        {
            var user = new SecurityIdentifier(Marshal.ReadIntPtr(info));
            RawAcl acl = ReadDefaultDacl(token);
            bool allowsUser = false, allowsSystem = false, allowsAdmin = false;
            if (acl != null)
                foreach (GenericAce entry in acl)
                {
                    var ace = entry as CommonAce;
                    if (ace == null || ace.AceQualifier != AceQualifier.AccessAllowed) continue;
                    allowsUser |= ace.SecurityIdentifier.Equals(user);
                    allowsSystem |= ace.SecurityIdentifier.IsWellKnown(WellKnownSidType.LocalSystemSid);
                    allowsAdmin |= ace.SecurityIdentifier.IsWellKnown(WellKnownSidType.BuiltinAdministratorsSid);
                }
            return "null=" + (acl == null) + "; user_allow=" + allowsUser +
                "; system_allow=" + allowsSystem + "; administrators_allow=" + allowsAdmin;
        }
        finally { Marshal.FreeHGlobal(info); }
    }

    private void NormalizeRestrictedDefaultDacl()
    {
        // CreatePipe with NULL security attributes takes its default DACL from
        // the creating token. LUA filtering can leave deny-only Administrators
        // as the only matching write grant, preventing the pipe's client open.
        // Change ONLY TokenDefaultDacl (6) on our new restricted token. The
        // original token, token owner, existing objects and machine ACLs stay as-is.
        // https://learn.microsoft.com/windows/win32/api/winnt/ns-winnt-token_default_dacl
        // https://learn.microsoft.com/windows/win32/api/namedpipeapi/nf-namedpipeapi-createpipe
        IntPtr userInfo = ReadToken(token, 1);
        IntPtr buffer = IntPtr.Zero;
        try
        {
            var user = new SecurityIdentifier(Marshal.ReadIntPtr(userInfo));
            var system = new SecurityIdentifier(WellKnownSidType.LocalSystemSid, null);
            var acl = new RawAcl(2, 2);
            acl.InsertAce(0, new CommonAce(AceFlags.None, AceQualifier.AccessAllowed, 0x10000000, user, false, null));
            acl.InsertAce(1, new CommonAce(AceFlags.None, AceQualifier.AccessAllowed, 0x10000000, system, false, null));
            byte[] expected = new byte[acl.BinaryLength];
            acl.GetBinaryForm(expected, 0);
            buffer = Marshal.AllocHGlobal(expected.Length);
            Marshal.Copy(expected, 0, buffer, expected.Length);
            var info = new TokenDefaultDacl { acl = buffer };
            Require(SetTokenInformation(token, 6, ref info, Marshal.SizeOf<TokenDefaultDacl>()),
                "Set current-user and SYSTEM defaults on new restricted token only");
            RawAcl actual = ReadDefaultDacl(token);
            if (actual == null || actual.BinaryLength != expected.Length)
                throw new InvalidOperationException("Restricted default DACL did not round-trip.");
            byte[] observed = new byte[actual.BinaryLength];
            actual.GetBinaryForm(observed, 0);
            for (int i = 0; i < expected.Length; i++)
                if (expected[i] != observed[i]) throw new InvalidOperationException("Unexpected restricted default DACL.");
        }
        finally
        {
            if (buffer != IntPtr.Zero) Marshal.FreeHGlobal(buffer);
            Marshal.FreeHGlobal(userInfo);
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
        IntPtr nullStream = IntPtr.Zero, attributes = IntPtr.Zero, handleList = IntPtr.Zero;
        bool attributesInitialized = false, resumed = false;
        try
        {
            // NULL inherits the runner's existing desktop/window station;
            // never assume the hosted runner uses winsta0\default or edit its ACL.
            var startup = new StartupInfoEx();
            startup.startup.cb = Marshal.SizeOf<StartupInfoEx>();
            // Valid NUL stdio avoids stale parent handles when Python launches
            // its read-only PowerShell subprocess. Inherit exactly this handle;
            // no runner, token, process, pipe, or job handle can leak to the child.
            var security = new SecurityAttributes { length = Marshal.SizeOf<SecurityAttributes>(), inherit = true };
            nullStream = CreateFile("NUL", 0xc0000000, 3, ref security, 3, 0, IntPtr.Zero);
            if (nullStream == new IntPtr(-1)) throw new Win32Exception(Marshal.GetLastWin32Error(), "Open synthetic NUL stdio");
            UIntPtr size = UIntPtr.Zero;
            InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref size);
            if (size == UIntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error(), "Measure inherited-handle allowlist");
            attributes = Marshal.AllocHGlobal(checked((int)size.ToUInt64()));
            Require(InitializeProcThreadAttributeList(attributes, 1, 0, ref size), "Initialize inherited-handle allowlist");
            attributesInitialized = true;
            handleList = Marshal.AllocHGlobal(IntPtr.Size);
            Marshal.WriteIntPtr(handleList, nullStream);
            Require(UpdateProcThreadAttribute(attributes, 0, new IntPtr(0x00020002), // PROC_THREAD_ATTRIBUTE_HANDLE_LIST
                handleList, new UIntPtr((uint)IntPtr.Size), IntPtr.Zero, IntPtr.Zero), "Allow only synthetic NUL inheritance");
            startup.attributes = attributes;
            startup.startup.flags = 0x100; // STARTF_USESTDHANDLES
            startup.startup.stdInput = startup.startup.stdOutput = startup.startup.stdError = nullStream;
            var command = new StringBuilder("\"" + executable + "\"" + (arguments == "" ? "" : " " + arguments));
            Require(CreateProcessAsUser(token, executable, command, IntPtr.Zero, IntPtr.Zero, true,
                CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | 0x00080000, // EXTENDED_STARTUPINFO_PRESENT
                environmentBlock, directory, ref startup, out info),
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
            if (attributesInitialized) DeleteProcThreadAttributeList(attributes);
            if (attributes != IntPtr.Zero) Marshal.FreeHGlobal(attributes);
            if (handleList != IntPtr.Zero) Marshal.FreeHGlobal(handleList);
            if (nullStream != IntPtr.Zero && nullStream != new IntPtr(-1)) CloseHandle(nullStream);
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
