import ChatWindow from "@/components/ChatWindow";
import ErrorBoundary from "@/components/ErrorBoundary";

export default function Home() {
  return <ErrorBoundary><ChatWindow /></ErrorBoundary>;
}
