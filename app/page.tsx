import { redirect } from "next/navigation";

/** Landing page is the public vendor directory (carry_class_vendor_data). Import lives under /import. */
export default function HomePage() {
  redirect("/directory");
}
