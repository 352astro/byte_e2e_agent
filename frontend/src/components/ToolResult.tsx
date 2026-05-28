import React from "react";
import { ToolResultCard } from "./ToolCards";

interface ToolResultProps {
    toolName: string;
    result: string;
    toolArgs?: Record<string, unknown>;
}

const ToolResult = React.memo(function ToolResult({
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
});

export default ToolResult;

