namespace D3sk.AgentCli.Local;

/// <summary>A local model did not load or did not answer. The message is for the owner and never holds the key.</summary>
public sealed class MlxException(string message) : Exception(message)
{
}
