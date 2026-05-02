import { google } from "googleapis";
import { env } from "@/lib/env";

export async function syncToSheets(rows: Array<Record<string, string | number | null>>) {
  if (!env.GOOGLE_CLIENT_EMAIL || !env.GOOGLE_PRIVATE_KEY || !env.GOOGLE_SHEETS_ID) {
    throw new Error("Google Sheets env vars are not configured.");
  }

  const auth = new google.auth.JWT({
    email: env.GOOGLE_CLIENT_EMAIL,
    key: env.GOOGLE_PRIVATE_KEY.replace(/\\n/g, "\n"),
    scopes: ["https://www.googleapis.com/auth/spreadsheets"]
  });

  const sheets = google.sheets({ version: "v4", auth });
  const values = rows.map((row) => Object.values(row));
  await sheets.spreadsheets.values.update({
    spreadsheetId: env.GOOGLE_SHEETS_ID,
    range: "Sheet1!A2",
    valueInputOption: "RAW",
    requestBody: { values }
  });
}
