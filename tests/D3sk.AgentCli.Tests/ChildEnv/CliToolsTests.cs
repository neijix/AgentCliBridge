using D3sk.AgentCli.ChildEnv;

namespace D3sk.AgentCli.Tests.ChildEnv;

public class CliToolsTests
{
    [Fact]
    public void The_PATH_hit_wins_then_the_usual_places_then_the_bare_name()
    {
        var env = (string v) => v == "ProgramFiles" ? @"C:\Program Files" : null;
        Assert.Equal(@"C:\p\npm.cmd", CliTools.WindowsTool("npm.cmd", n => @"C:\p\" + n, _ => "", env));
        IEnumerable<string>? seen = null;
        var found = CliTools.WindowsTool("npm.cmd", _ => null, p => { seen = p; return p.First(); }, env);
        Assert.Equal(@"C:\Program Files\nodejs\npm.cmd", found);
        Assert.Equal(@"C:\Program Files\nodejs\npm.cmd", Assert.Single(seen!));
        Assert.Equal("winget", CliTools.WindowsTool("winget", _ => null, _ => "", env));
        Assert.Equal("other", CliTools.WindowsTool("other", _ => null, _ => "", env));
    }

    [Fact]
    public void Which_finds_an_executable_on_the_given_PATH_only()
    {
        if (OperatingSystem.IsWindows())
        {
            return;
        }
        var dir = Directory.CreateTempSubdirectory("which").FullName;
        try
        {
            var tool = Path.Combine(dir, "mytool");
            File.WriteAllText(tool, "#!/bin/sh\n");
            Assert.Null(CliTools.Which("mytool", dir, false));
            File.SetUnixFileMode(tool, UnixFileMode.UserRead | UnixFileMode.UserExecute);
            Assert.Equal(tool, CliTools.Which("mytool", "/nonexistent:" + dir, false));
            Assert.Equal(tool, CliTools.FirstExecutable(["", "/nope", tool]));
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }
}
