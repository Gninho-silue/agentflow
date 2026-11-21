import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TaskInput } from "./TaskInput";

function setup(props: Partial<Parameters<typeof TaskInput>[0]> = {}) {
  const onRun = vi.fn().mockResolvedValue(undefined);
  const user = userEvent.setup();
  render(<TaskInput onRun={onRun} loading={false} error={null} {...props} />);
  return {
    user,
    onRun,
    textarea: screen.getByPlaceholderText(/analyze a csv file/i),
    submit: screen.getByRole("button", { name: /run agentflow/i }),
    fileInput: screen.getByLabelText(/upload csv, json, or txt file/i) as HTMLInputElement,
  };
}

function makeFile(name: string, size = 10): File {
  const file = new File(["x"], name, { type: "text/plain" });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

describe("TaskInput — task validation", () => {
  it("disables submit until the task has at least 3 non-blank characters", async () => {
    const { user, textarea, submit } = setup();
    expect(submit).toBeDisabled();

    await user.type(textarea, "  a ");
    expect(submit).toBeDisabled();

    await user.clear(textarea);
    await user.type(textarea, "abc");
    expect(submit).toBeEnabled();
  });

  it("shows the character counter and blocks tasks over 2000 characters", () => {
    const { textarea, submit } = setup();
    fireEvent.change(textarea, { target: { value: "x".repeat(2001) } });

    expect(screen.getByText("2001 / 2000")).toHaveClass("text-bad");
    expect(submit).toBeDisabled();
  });

  it("calls onRun with the trimmed task and no file", async () => {
    const { user, textarea, submit, onRun } = setup();
    await user.type(textarea, "   Summarize sales   ");
    await user.click(submit);

    expect(onRun).toHaveBeenCalledWith("Summarize sales", null);
  });

  it("shows a running state while loading", () => {
    render(<TaskInput onRun={vi.fn()} loading error={null} />);
    expect(screen.getByRole("button", { name: /running/i })).toBeDisabled();
  });

  it("displays the error passed by the parent", () => {
    setup({ error: "Backend unreachable" });
    expect(screen.getByText("Backend unreachable")).toBeInTheDocument();
  });
});

describe("TaskInput — example preset", () => {
  it("fills the task and file from a preset and submits them", async () => {
    const onRun = vi.fn().mockResolvedValue(undefined);
    const file = makeFile("monthly_sales.csv");
    const { rerender } = render(<TaskInput onRun={onRun} loading={false} error={null} preset={null} />);

    rerender(<TaskInput onRun={onRun} loading={false} error={null} preset={{ task: "Analyze sales", file, nonce: 1 }} />);

    expect(screen.getByPlaceholderText(/analyze a csv file/i)).toHaveValue("Analyze sales");
    expect(screen.getByText("monthly_sales.csv")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /run agentflow/i }));
    expect(onRun).toHaveBeenCalledWith("Analyze sales", file);
  });
});

describe("TaskInput — upload", () => {
  it("accepts a CSV file, shows its name and sends it on submit", async () => {
    const { user, textarea, submit, fileInput, onRun } = setup();
    const file = makeFile("sales.csv");

    await user.upload(fileInput, file);
    expect(screen.getByText("sales.csv")).toBeInTheDocument();

    await user.type(textarea, "Analyze the file");
    await user.click(submit);
    expect(onRun).toHaveBeenCalledWith("Analyze the file", file);
  });

  it.each(["script.py", "image.png", "noextension"])("rejects %s with a type error", (name) => {
    const { fileInput } = setup();
    fireEvent.change(fileInput, { target: { files: [makeFile(name)] } });

    expect(screen.getByText(/is not allowed\. Upload a \.csv, \.json, or \.txt file\./)).toBeInTheDocument();
    expect(screen.queryByText(name)).not.toBeInTheDocument();
  });

  it("rejects files larger than 10 MB", () => {
    const { fileInput } = setup();
    fireEvent.change(fileInput, { target: { files: [makeFile("big.csv", 10 * 1024 * 1024 + 1)] } });

    expect(screen.getByText("File exceeds the 10 MB size limit.")).toBeInTheDocument();
    expect(screen.queryByText("big.csv")).not.toBeInTheDocument();
  });

  it("accepts a dropped JSON file", () => {
    setup();
    const dropZone = screen.getByText(/drop file here/i).parentElement as HTMLElement;
    fireEvent.drop(dropZone, { dataTransfer: { files: [makeFile("catalog.json")] } });

    expect(screen.getByText("catalog.json")).toBeInTheDocument();
  });

  it("removes the selected file", async () => {
    const { user, fileInput } = setup();
    await user.upload(fileInput, makeFile("notes.txt"));

    await user.click(screen.getByRole("button", { name: /remove file/i }));
    expect(screen.queryByText("notes.txt")).not.toBeInTheDocument();
    expect(screen.getByText(/drop file here/i)).toBeInTheDocument();
  });
});
