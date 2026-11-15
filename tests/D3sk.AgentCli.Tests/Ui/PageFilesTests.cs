namespace D3sk.AgentCli.Tests.Ui;

/// <summary>
/// The package ships the 19 page files the consuming hub serves at /acb. Each is byte-identical
/// to the file at AgentCliBridge rev 8ed5e7c84e27 (branch python-d3skhand, agent_cli_bridge/ui/).
/// </summary>
public class PageFilesTests
{
    private static readonly (string Name, string Sha256)[] Expected =
    [
        ("chatbox.css", "1e8aa8f33f2833a1c9cd23a316c38df9ff832b425a01f12572024f6a069088f1"),
        ("components.js", "082a58dbd2ae7133fb6fbaeb91dba5c981872bccbd1f9ca4a15aa06eb6e0f132"),
        ("composer.js", "eda80c2d4465889bd2e28ec7825baf34f000c9799bcd247e902a9f96bdf6f3cd"),
        ("composer_menu.js", "c62c8a3484c140653a5905aa014f94e1bf6e6473834a5d0ef6122b43938b42bf"),
        ("icons.js", "4122b8c538707fad5ec86e2798478160de9bff48c40ff3f77f61d2ff00c72183"),
        ("model_agents.js", "047b3f76c2d2ae333a555c17002efc25ec0a8f1ff3916bb5fc8cd04610ecadab"),
        ("model_catalog.js", "c4a6a9b55ec4ccc77c2bc6fbdd475b11ac0dbe49c76ec706e3234d40047d1e52"),
        ("model_effort.js", "443df43b18f8248aba5e8dc2678d9dfdeadfdecb3f465379a1f1815a9c687bea"),
        ("model_names.js", "96c342c5503b6b4c1f831c5b5f37215bcd737fab91dbee2e4ec255241cd86755"),
        ("model_picker.js", "5d2fdb85292e5cee9fb0ee5bcffdbe4e78e512f3ed435ee30d9bd68a371c16ca"),
        ("model_ranking.js", "2626c9aa780662346d7a1b1a8e5730a8c46e52ba1c1a5bba42f68c55d16db480"),
        ("model_tags.js", "279ca1842d60ec6d7df76a000e1e033ff58396743eb326bdc2f8451672f48a27"),
        ("models.js", "5279d3534264120debea1c8229d092db4fb621416fafb6d4315edd9421d5510d"),
        ("palette.css", "c8a4bf69c76bd3415654316ee891e49ef8fd03aca5635caac38f442d4019b8f6"),
        ("permission_modes.js", "b40069932a740719e768e49c3580eaa02fe13dee2501a4cc4ad03c85daeaf24f"),
        ("settings.css", "90c89cb372401206802e43fa49c5e9a2965cb14dc513e3b782e0fc3cc388b2b0"),
        ("settings_agents.js", "17f486c0319cf0d9f9635905f1f0e20db9f9371f4c6f4b0089e74bbc90a49ec2"),
        ("settings_models.js", "973adef476d5f6060b83cea1a923994b7d7279525a4f732c9b6db870034dd7b0"),
        ("stream.js", "1f3b90b37b2b37f0d248aaa4d587df6ae7cdaf6ef9b92f37a9f9b3cc117f0f5d"),
    ];

    private static string UiDir()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "D3sk.AgentCli.slnx")))
            dir = dir.Parent;
        Assert.NotNull(dir);
        return Path.Combine(dir.FullName, "src", "D3sk.AgentCli", "ui");
    }

    [Fact]
    public void ShipsExactlyTheNineteenPageFiles()
    {
        var actual = Directory.GetFiles(UiDir()).Select(Path.GetFileName).Order(StringComparer.Ordinal);
        Assert.Equal(Expected.Select(e => e.Name).Order(StringComparer.Ordinal), actual);
        Assert.Equal(19, Expected.Length);
    }

    [Fact]
    public void EveryPageFileIsByteIdenticalToThePinnedRev()
    {
        foreach (var (name, sha) in Expected)
        {
            var hash = Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(Path.Combine(UiDir(), name))));
            Assert.True(sha == hash, $"{name} differs from rev 8ed5e7c");
        }
    }
}
