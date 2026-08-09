import { CompanyView } from "@/components/company-view";

export default async function CompanyPage({
  params,
}: {
  params: Promise<{ ticker: string }>;
}) {
  const { ticker } = await params;
  return <CompanyView ticker={ticker.toUpperCase()} />;
}
