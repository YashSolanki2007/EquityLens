import { SearchView } from "@/components/search-view";

export default async function SearchPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <SearchView id={id} />;
}
