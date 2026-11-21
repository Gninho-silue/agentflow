/** One-click demo examples. Datasets live in public/examples (served by Vite). */
export interface Example {
  id: string;
  label: string;
  description: string;
  task: string;
  fileName: string;
}

export const EXAMPLES: Example[] = [
  {
    id: "sales",
    label: "Monthly sales",
    description: "CSV · revenue by month, region and category",
    task: "Analyze the monthly sales CSV: total revenue per region and per category, the month-over-month trend, and plot a bar chart of revenue by month.",
    fileName: "monthly_sales.csv",
  },
  {
    id: "catalog",
    label: "Product catalog",
    description: "JSON · prices, stock and ratings",
    task: "Analyze the product catalog JSON: average price and rating per category, list the products that are out of stock or have fewer than 10 units, and plot a chart of stock by category.",
    fileName: "product_catalog.json",
  },
  {
    id: "reviews",
    label: "Customer reviews",
    description: "TXT · 18 short reviews",
    task: "Analyze the customer reviews text file: count the reviews that mention delivery problems (late, damaged, wrong) and product defects (broken, stopped working), and summarize the overall sentiment.",
    fileName: "customer_reviews.txt",
  },
];

/** Download an example dataset and wrap it in a File, as if the visitor had uploaded it. */
export async function loadExampleFile(example: Example, fetcher: typeof fetch = fetch): Promise<File> {
  const response = await fetcher(`${import.meta.env.BASE_URL}examples/${example.fileName}`);
  if (!response.ok) {
    throw new Error(`Could not load the example file (${response.status}).`);
  }
  // All example datasets are small UTF-8 text files.
  const content = await response.text();
  return new File([content], example.fileName, { type: "text/plain" });
}
