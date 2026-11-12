using System.Security.Cryptography;

namespace D3sk.AgentCli.Tests;

/// <summary>
/// tests/streams and tests/wire are byte copies of the Python repo at its freeze tag; the
/// manifest records the tag and every file's SHA-256. A changed, missing or extra file fails.
/// </summary>
public class FrozenFixturesTests
{
    private static readonly string Root = FindRoot();

    private static string FindRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "global.json")))
        {
            dir = dir.Parent;
        }
        return dir?.FullName ?? throw new InvalidOperationException("repo root (global.json) not found");
    }

    private static (string Tag, Dictionary<string, string> Files) ReadManifest()
    {
        var files = new Dictionary<string, string>(StringComparer.Ordinal);
        string tag = "";
        foreach (var line in File.ReadAllLines(Path.Combine(Root, "tests", "frozen-manifest.txt")))
        {
            if (line.StartsWith("tag ", StringComparison.Ordinal))
            {
                tag = line[4..].Trim();
            }
            else if (line.Length > 65 && line[64] == ' ')
            {
                files[line[65..]] = line[..64];
            }
        }
        return (tag, files);
    }

    private static string Hash(string relative) =>
        Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(Path.Combine(Root, relative))));

    [Fact]
    public void Manifest_names_the_freeze_tag_and_lists_files()
    {
        var (tag, files) = ReadManifest();
        Assert.Equal("v0.3.0", tag);
        Assert.NotEmpty(files);
    }

    [Fact]
    public void Every_manifest_file_matches_its_hash()
    {
        var (_, files) = ReadManifest();
        foreach (var (path, expected) in files)
        {
            Assert.True(File.Exists(Path.Combine(Root, path)), $"missing: {path}");
            Assert.True(expected == Hash(path), $"differs from the freeze tag: {path}");
        }
    }

    [Fact]
    public void No_file_outside_the_manifest_sits_in_the_frozen_folders()
    {
        var (_, files) = ReadManifest();
        foreach (var folder in new[] { "streams", "wire" })
        {
            foreach (var full in Directory.EnumerateFiles(Path.Combine(Root, "tests", folder), "*", SearchOption.AllDirectories))
            {
                var relative = Path.GetRelativePath(Root, full).Replace('\\', '/');
                Assert.True(files.ContainsKey(relative), $"not in the manifest: {relative}");
            }
        }
    }
}
