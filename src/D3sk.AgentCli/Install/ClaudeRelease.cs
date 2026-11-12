namespace D3sk.AgentCli.Install;

/// <summary>
/// Replaces the <c>claude-code@latest</c> Homebrew cask's binary with the one Anthropic publishes,
/// when Homebrew's formula still lags (<c>brew upgrade</c> then says "already installed"). The binary
/// is saved beside the cask file, its header and (macOS) signature are checked, and only then does
/// it replace the file; any failure deletes the download and leaves the old binary as it was.
/// </summary>
public sealed class ClaudeRelease(ScriptDownloader downloader, IProcessRunner runner)
{
    /// <summary>The only host a Claude binary is fetched from.</summary>
    public const string Host = "downloads.claude.ai";

    /// <summary>The smallest and largest size a Claude binary can be.</summary>
    public const long MinBytes = 20L * 1024 * 1024, MaxBytes = 400L * 1024 * 1024;

    private const string SignId = "com.anthropic.claude-code";
    private const string TeamId = "Q6L2SF6YDW";
    private const string DownloadName = ".claude.agent-cli-bridge-download";
    private static readonly TimeSpan ToolTimeout = TimeSpan.FromSeconds(60);

    /// <summary>The binary URL the <c>claude-code@latest</c> cask itself uses; <paramref name="os"/> is <c>darwin</c> or <c>linux</c>.</summary>
    /// <exception cref="InstallStepException">The version is not a plain number, or no build exists for the platform.</exception>
    public static string Url(string version, string os, string arch)
    {
        if (version.Length == 0 || !version.All(c => char.IsAsciiDigit(c) || c == '.') || version.Split('.').Any(p => p.Length == 0) || !version.Contains('.'))
        {
            throw new InstallStepException("plan", $"refusing a Claude release version that is not a plain number: '{version}'");
        }
        var arch2 = arch switch { "arm64" or "aarch64" => "arm64", "x64" or "x86_64" or "amd64" => "x64", _ => "" };
        if (os is not ("darwin" or "linux") || arch2.Length == 0)
        {
            throw new InstallStepException("plan", $"no Claude Code build is published for {os} {arch}");
        }
        return $"https://{Host}/claude-code-releases/{version}/{os}-{arch2}/claude";
    }

    /// <summary>Whether <paramref name="resolved"/> is the <c>claude</c> file inside <c>Caskroom/claude-code@latest</c>.</summary>
    public static bool IsLatestCaskBinary(string resolved)
    {
        var parts = CliPath.Parts(resolved, windows: false);
        var at = Array.IndexOf(parts, "Caskroom");
        return parts.Length > 0 && parts[0] == "/" && parts[^1] == "claude" && at >= 0 && at + 1 < parts.Length && parts[at + 1] == "claude-code@latest";
    }

    /// <summary>Install Anthropic's <paramref name="version"/> over <paramref name="dest"/>; returns what to tell the owner.</summary>
    public async Task<InstallOutcome> InstallPublishedAsync(string dest, string version, string os, string arch, CancellationToken ct)
    {
        var info = new FileInfo(dest);
        string tmp = Path.Combine(info.DirectoryName ?? ".", DownloadName);
        try
        {
            if (info.LinkTarget is not null || !info.Exists || !IsLatestCaskBinary(Path.GetFullPath(dest)))
            {
                return InstallOutcome.Failed("plan", "refusing to replace a Claude binary that is not the claude-code@latest cask file");
            }
            await downloader.SaveAsync(Url(version, os, arch), tmp, MaxBytes, MinBytes, ct).ConfigureAwait(false);
            await CheckAsync(tmp, os, ct).ConfigureAwait(false);
            if (!OperatingSystem.IsWindows())
            {
                File.SetUnixFileMode(tmp, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute | UnixFileMode.GroupRead | UnixFileMode.GroupExecute | UnixFileMode.OtherRead | UnixFileMode.OtherExecute);
            }
            File.Move(tmp, dest, overwrite: true);
            if (os == "darwin")
            {
                // The cask symlink still points here: the mark has to be gone before the next launch.
                await runner.RunAsync(["/usr/bin/xattr", "-d", "com.apple.quarantine", dest], ToolTimeout, ct).ConfigureAwait(false);
            }
            return InstallOutcome.Succeeded($"Installed Anthropic's Claude Code {version} over the Homebrew cask (its formula was still behind).");
        }
        catch (InstallStepException ex)
        {
            return InstallOutcome.Failed(ex.Step, ex.Message);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return InstallOutcome.Failed("run", $"could not install Claude Code {version}: {ex.Message}");
        }
        finally
        {
            File.Delete(tmp);
        }
    }

    private async Task CheckAsync(string path, string os, CancellationToken ct)
    {
        var header = new byte[4];
        await using (var stream = File.OpenRead(path))
        {
            await stream.ReadExactlyAsync(header, ct).ConfigureAwait(false);
        }
        if (os == "linux")
        {
            Require(header.AsSpan().SequenceEqual("\x7fELF"u8), "the downloaded Claude binary is not a Linux executable");
            return;
        }
        Require(header.AsSpan().SequenceEqual(new byte[] { 0xcf, 0xfa, 0xed, 0xfe }), "the downloaded Claude binary is not a macOS executable");
        var verified = await runner.RunAsync(["/usr/bin/codesign", "--verify", "--strict", path], ToolTimeout, ct).ConfigureAwait(false);
        Require(verified.ExitCode == 0, $"Anthropic's signature check failed: {verified.Output}");
        var details = await runner.RunAsync(["/usr/bin/codesign", "-d", "--verbose=4", path], ToolTimeout, ct).ConfigureAwait(false);
        Require(details.Output.Contains($"Identifier={SignId}", StringComparison.Ordinal) && details.Output.Contains($"TeamIdentifier={TeamId}", StringComparison.Ordinal),
            "the downloaded Claude binary is not signed by Anthropic");
    }

    private static void Require(bool ok, string message)
    {
        if (!ok)
        {
            throw new InstallStepException("verify", message);
        }
    }
}
