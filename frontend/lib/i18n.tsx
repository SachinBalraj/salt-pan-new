"use client";

import { createContext, useContext, useState, ReactNode } from "react";

export type Lang = "en" | "ta";

const LangContext = createContext<{ lang: Lang; setLang: (l: Lang) => void }>({
  lang: "en",
  setLang: () => {},
});

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>("en");
  return (
    <LangContext.Provider value={{ lang, setLang }}>
      {children}
    </LangContext.Provider>
  );
}

export function useLang() {
  return useContext(LangContext);
}

export const LANG_LABEL: Record<Lang, string> = {
  en: "English",
  ta: "தமிழ்",
};

// ---------------------------------------------------------------------------
// Farmer instruction strings (from the recommendation engine) + UI labels.
// "ta" is a best-effort, everyday Tamil translation for a Tamil Nadu farmer.
// UI chrome stays English; farmer instructions and status words translate.
// ---------------------------------------------------------------------------
const TA: Record<string, string> = {
  // --- recommendation action titles --------------------------------------
  "Harvest now before the rain": "மழைக்கு முன் இப்போதே அறுவடை செய்யுங்கள்",
  "Schedule harvest in the next 1-2 days":
    "அடுத்த 1-2 நாட்களில் அறுவடையைத் திட்டமிடுங்கள்",
  "Protect the pan from incoming rain":
    "வரவிருக்கும் மழையிலிருந்து பானைப் பாதுகாக்கவும்",
  "Keep the brine crystallising":
    "உப்புநீர் தொடர்ந்து படிகமாகட்டும்",
  "Pump away the dilute top water":
    "மேலே உள்ள தண்ணீரை வெளியேற்றவும்",
  "Store the concentrated brine before the rain":
    "மழைக்கு முன் செறிவூட்டப்பட்ட உப்புநீரைச் சேமிக்கவும்",
  "Pan is on track - keep monitoring":
    "பான் சரியாக உள்ளது - தொடர்ந்து கண்காணிக்கவும்",
  "Harvest now": "இப்போதே அறுவடை செய்யுங்கள்",
  "Harvest soon": "விரைவில் அறுவடை செய்யுங்கள்",

  // --- instruction steps ---------------------------------------------------
  "Harvest today or before": "இன்றோ அல்லது அதற்கு முன்பே அறுவடை செய்யுங்கள்",
  "Mobilise labour and transport immediately.":
    "உடனடியாக தொழிலாளர்களையும் போக்குவரத்தையும் திரட்டுங்கள்.",
  "Move harvested salt under cover before the rain arrives.":
    "மழை வருவதற்கு முன் அறுவடை உப்பை மூடி வைக்கவும்.",
  "Plan the harvest for the next clear, dry day.":
    "அடுத்த தெளிவான, வெயில் நாளில் அறுவடை செய்யத் திட்டமிடுங்கள்.",
  "Line up labour, baskets and transport in advance.":
    "முன்கூட்டியே தொழிலாளர்கள், கூடைகள், போக்குவரத்து தயார் செய்யுங்கள்.",
  "Re-check the forecast each morning before cutting.":
    "அறுவடைக்கு முன் ஒவ்வொரு காலையிலும் வானிலை முன்னறிவிப்பை சரிபார்க்கவும்.",
  "Cover harvested stockpiles with tarpaulin.":
    "அறுவடை செய்த உப்பு குவியல்களை தார்ப்பாய்களால் மூடவும்.",
  "Open drain outlets so rainwater leaves the beds quickly.":
    "மழைநீர் விரைவாக வெளியேற கால்வாய்களைத் திறக்கவும்.",
  "Stop adding brine to crystallising beds until the event passes.":
    "மழை முடியும் வரை படிகக் குளத்தில் உப்புநீரைச் சேர்க்க வேண்டாம்.",
  "Keep brine shallow and let evaporation continue.":
    "உப்புநீரை ஆழம் குறைவாக வைத்து ஆவியாவதைத் தொடர விடுங்கள்.",
  "Re-check density daily.": "தினமும் அடர்த்தியை சரிபார்க்கவும்.",
  "Re-run the forecast when the weather changes.":
    "வானிலை மாறும்போது முன்னறிவிப்பை மீண்டும் இயக்கவும்.",
  "Pump the diluted surface water into the reserve condensers.":
    "நீர்த்த மேற்பரப்பு நீரை காப்பு குளங்களுக்கு பம்ப் செய்யவும்.",
  "Let evaporation concentrate what remains.":
    "மீதமுள்ளவற்றை ஆவியாக்கி செறிவாக்கவும்.",
  "Monitor density daily until the crystallisation zone (>= 25°Bé).":
    "படிகமாகும் நிலை வரை (25°Bé) தினமும் அடர்த்தியை கண்காணிக்கவும்.",
  "Transfer the mother brine into covered reserve beds.":
    "தாய் உப்புநீரை மூடப்பட்ட காப்பு குளங்களுக்கு மாற்றவும்.",
  "Fill reserve capacity before the storm arrives.":
    "புயல் வருவதற்கு முன் காப்பு குளங்களை நிரப்பவும்.",
  "Return the brine to the crystallisers after the event.":
    "மழைக்குப் பிறகு உப்புநீரை படிகக் குளங்களுக்கு திருப்பி விடவும்.",
  "Keep refreshing the forecast daily.":
    "தினமும் வானிலை முன்னறிவிப்பை மீண்டும் புதுப்பிக்கவும்.",
  "Continue standard crystallisation checks.":
    "வழக்கமான படிகமாக்கல் சோதனைகளைத் தொடரவும்.",
  "Review the twin state again next shift.":
    "அடுத்த சீட் நேரத்தில் ட்வின் நிலையை மீண்டும் பார்க்கவும்.",
  "Keep monitoring": "தொடர்ந்து கண்காணிக்கவும்",

  // --- status words ---------------------------------------------------------
  pending: "நிலுவையில்",
  active: "செயலில்",
  accepted: "ஏற்கப்பட்டது",
  accepted_: "ஏற்கப்பட்டது",
  declined: "நிராகரிக்கப்பட்டது",
  rejected: "நிராகரிக்கப்பட்டது",
  completed: "முடிந்தது",
  expired: "காலாவதியானது",
  low: "குறைவு",
  medium: "நடுத்தரம்",
  high: "அதிகம்",

  // --- dashboard / farmer labels ---------------------------------------------
  "Recommended action": "பரிந்துரைக்கப்பட்ட செயல்",
  "Recommended action:": "பரிந்துரைக்கப்பட்ட செயல்:",
  "Active alerts": "செயலில் உள்ள எச்சரிக்கைகள்",
  "Last update": "கடைசி புதுப்பிப்பு",
};

// Word-level fallback map used for sentences we did not translate verbatim.
const WORD_MAP: [RegExp, string][] = [
  [/\bharvest\b/g, "அறுவடை"],
  [/\bharvesting\b/g, "அறுவடை"],
  [/\brain\b/g, "மழை"],
  [/\bbrine\b/g, "உப்புநீர்"],
  [/\bsalt\b/g, "உப்பு"],
  [/\bwater\b/g, "தண்ணீர்"],
  [/\bpump\b/g, "பம்ப்"],
  [/\bprotect\b/g, "பாதுகாக்கவும்"],
  [/\bcover\b/g, "மூடவும்"],
  [/\btransfer\b/g, "மாற்றவும்"],
  [/\bstored?\b/g, "சேமிக்க"],
  [/\bstore\b/g, "சேமிக்கவும்"],
  [/\bmonitor(ing)?\b/g, "கண்காணிக்க"],
  [/\bdensity\b/g, "அடர்த்தி"],
  [/\bforecast\b/g, "முன்னறிவிப்பு"],
  [/\bevaporation\b/g, "ஆவியாதல்"],
  [/\btemperature\b/g, "வெப்பநிலை"],
  [/\byield\b/g, "மகசூல்"],
  [/\blabour\b/g, "தொழிலாளர்கள்"],
  [/\btransport\b/g, "போக்குவரத்து"],
];

export function t(text: string | undefined | null, lang: Lang): string {
  if (!text) return text ?? "";
  if (lang === "en") return text;
  const exact = TA[text];
  if (exact !== undefined) return exact;
  const key = text.replace(/\.$/, "");
  if (TA[key]) return TA[key];
  let out = text;
  for (const [re, w] of WORD_MAP) out = out.replace(re, w);
  return out;
}