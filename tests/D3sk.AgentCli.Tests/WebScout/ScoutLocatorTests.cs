using D3sk.AgentCli.WebScout;

namespace D3sk.AgentCli.Tests.WebScout;

public sealed class ScoutLocatorTests : IDisposable
{
    private readonly string _dir = Directory.CreateTempSubdirectory("scoutloc").FullName;

    public void Dispose() => Directory.Delete(_dir, recursive: true);

    private string Checkout(string root)
    {
        var folder = Path.Combine(_dir, root, "D3SKWEBSCOUT");
        var python = ScoutLocator.VenvPython(folder);
        Directory.CreateDirectory(Path.GetDirectoryName(python)!);
        File.WriteAllText(python, "");
        Directory.CreateDirectory(Path.Combine(folder, "src", "d3skwebscout"));
        return folder;
    }

    [Trait("Preserve", "P23")]
    [Fact]
    public void Candidates_are_the_explicit_folder_alone_or_the_code_roots()
    {
        Assert.Equal(["/x/scout"], ScoutLocator.DefaultCandidates(n => n == "D3SKWEBSCOUT_DIR" ? "/x/scout" : "/y", "/h"));
        Assert.Equal(
            [Path.Combine("/y", "D3SKWEBSCOUT"), Path.Combine("/h", "Code", "D3SKWEBSCOUT"), Path.Combine("/h", "CODE", "D3SKWEBSCOUT")],
            ScoutLocator.DefaultCandidates(n => n == "AI_CODE_ROOT" ? "/y" : null, "/h"));
        Assert.Equal(
            [Path.Combine("/h", "Code", "D3SKWEBSCOUT"), Path.Combine("/h", "CODE", "D3SKWEBSCOUT")],
            ScoutLocator.DefaultCandidates(_ => null, "/h"));
    }

    [Trait("Preserve", "P23")]
    [Fact]
    public void An_installed_checkout_is_found_and_an_empty_folder_is_skipped()
    {
        var empty = Path.Combine(_dir, "other", "D3SKWEBSCOUT");
        Directory.CreateDirectory(empty);
        var installed = Checkout("code");

        Assert.Equal(Path.GetFullPath(installed), ScoutLocator.FindCheckout([empty, installed]));
        Assert.Null(ScoutLocator.FindCheckout([empty]));
    }

    [Trait("Preserve", "P23")]
    [Fact]
    public void A_checkout_only_under_home_CODE_is_found()
    {
        var installed = Checkout("CODE");
        var location = ScoutLocator.Locate(_ => null, _dir);

        // macOS and Windows disks are case-insensitive: ~/Code and ~/CODE are one folder there.
        var comparison = OperatingSystem.IsLinux() ? StringComparison.Ordinal : StringComparison.OrdinalIgnoreCase;
        Assert.Equal(Path.GetFullPath(installed), location!.Checkout, StringComparer.FromComparison(comparison));
        Assert.Equal(Path.Combine(location.Checkout, "data", "webscout.sock"), location.SocketPath);
        Assert.Null(ScoutLocator.Locate(_ => null, Path.Combine(_dir, "nowhere")));
    }

    [Trait("Preserve", "P23")]
    [Fact]
    public void The_venv_python_is_per_os()
    {
        Assert.Equal(Path.Combine("c", ".venv", "Scripts", "python.exe"), ScoutLocator.VenvPython("c", isWindows: true));
        Assert.Equal(Path.Combine("c", ".venv", "bin", "python"), ScoutLocator.VenvPython("c", isWindows: false));
    }

    [Trait("Preserve", "P23")]
    [Fact]
    public void The_port_is_the_environment_then_the_checkout_env_file_then_4820()
    {
        var checkout = Checkout("p");
        Assert.Equal(4820, ScoutLocator.ClientPort(checkout, _ => null));
        File.WriteAllText(Path.Combine(checkout, ".env"), "# c\nOTHER=1\nPORT=\"4900\"\n");
        Assert.Equal(4900, ScoutLocator.ClientPort(checkout, _ => null));
        Assert.Equal(4901, ScoutLocator.ClientPort(checkout, n => n == "WEBSCOUT_PORT" ? "4901" : null));
        Assert.Equal(4820, ScoutLocator.ClientPort(checkout, n => n == "WEBSCOUT_PORT" ? "abc" : null));
    }

    [Fact]
    public void Without_a_socket_the_endpoint_is_the_plain_port_that_the_client_refuses()
    {
        var checkout = Checkout("e");
        var location = new ScoutLocation(checkout, 4820, Path.Combine(checkout, "data", "webscout.sock"));
        Assert.Equal(ScoutTransport.PlainHttp, ScoutLocator.EndpointFor(location).Transport);

        Directory.CreateDirectory(Path.Combine(checkout, "data"));
        File.WriteAllText(location.SocketPath, "");
        Assert.Equal(ScoutTransport.UserSocket, ScoutLocator.EndpointFor(location).Transport);
    }
}
