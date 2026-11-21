import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EXAMPLES } from "../examples";
import { ExamplePicker } from "./ExamplePicker";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ExamplePicker", () => {
  it("offers three one-click examples", () => {
    render(<ExamplePicker onPick={vi.fn()} />);
    expect(screen.getAllByRole("button")).toHaveLength(3);
    expect(screen.getByRole("button", { name: /monthly sales/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /product catalog/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /customer reviews/i })).toBeInTheDocument();
  });

  it("loads the dataset and hands the task and file to the parent", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("month,revenue\n2026-01,10\n", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const onPick = vi.fn();
    render(<ExamplePicker onPick={onPick} />);

    await userEvent.click(screen.getByRole("button", { name: /monthly sales/i }));

    await waitFor(() => expect(onPick).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith("/examples/monthly_sales.csv");
    const [task, file] = onPick.mock.calls[0] as [string, File];
    expect(task).toBe(EXAMPLES[0].task);
    expect(file.name).toBe("monthly_sales.csv");
    const content = await new Promise<string>((resolve) => {
      const reader = new FileReader(); // jsdom's File has no .text()
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(file);
    });
    expect(content).toContain("2026-01");
  });

  it("shows an error when the dataset cannot be loaded", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 404 })));
    const onPick = vi.fn();
    render(<ExamplePicker onPick={onPick} />);

    await userEvent.click(screen.getByRole("button", { name: /customer reviews/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the example file (404).");
    expect(onPick).not.toHaveBeenCalled();
  });
});
