import { CustomerDetailPage } from "@/features/customers/components/customer-detail-page";

export default async function Page(props: PageProps<"/app/customers/[customerId]">) {
  const { customerId } = await props.params;
  return <CustomerDetailPage customerId={customerId} />;
}
