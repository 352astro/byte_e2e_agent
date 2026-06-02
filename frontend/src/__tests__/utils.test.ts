import { describe, expect, it } from "vitest";
import { extractToolMeta } from "../utils";

describe("extractToolMeta", () => {
  it("separates Write content from complete JSON args", () => {
    const { meta, rest } = extractToolMeta(
      '{"path":"docs/a.md","content":"# Title"}',
      "Write",
    );

    expect(meta.path).toBe("docs/a.md");
    expect(meta.content).toBeUndefined();
    expect(rest).toBe("# Title");
  });

  it("separates Write content from partial JSON args", () => {
    const { meta, rest } = extractToolMeta(
      '{"path":"docs/a.md","content":"# Ti',
      "Write",
    );

    expect(meta.path).toBe("docs/a.md");
    expect(rest).toBe("# Ti");
  });

  it("extracts Write meta before the long key appears", () => {
    const { meta, rest } = extractToolMeta('{"path":"docs/a.md"', "Write");

    expect(meta.path).toBe("docs/a.md");
    expect(rest).toBe("");
  });
});
