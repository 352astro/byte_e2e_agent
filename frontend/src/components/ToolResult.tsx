import { ToolResultCard } from "./ToolCards";

interface ToolResultProps {
    toolName: string;
    result: string;
    toolArgs?: Record<string, unknown>;
}

export default function ToolResult({
    toolName,
    result,
    toolArgs,
}: ToolResultProps) {
    return (
        <ToolResultCard
            toolName={toolName}
            result={result}
            toolArgs={toolArgs}
        />
    );
}
