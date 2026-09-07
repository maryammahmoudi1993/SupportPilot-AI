import { Spinner } from "@/components/ui/spinner";

/** Route-level loading UI, shown by Next.js while a page's data is being fetched. */
export default function Loading() {
  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <Spinner label="Loading page" />
    </main>
  );
}
