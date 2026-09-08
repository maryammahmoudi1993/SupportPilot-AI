import { TicketDetailPage } from "@/features/tickets/components/ticket-detail-page";

export default async function Page(props: PageProps<"/app/tickets/[ticketId]">) {
  const { ticketId } = await props.params;
  return <TicketDetailPage ticketId={ticketId} />;
}
