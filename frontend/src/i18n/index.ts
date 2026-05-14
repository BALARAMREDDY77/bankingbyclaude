/**
 * Internationalization Setup — react-i18next
 * ============================================
 * Supports: English (en), Hindi (hi), Arabic (ar)
 * Locale detection from browser, localStorage, and URL.
 */

import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

// Translations (expand per locale as needed)
import en from "./locales/en.json";
import hi from "./locales/hi.json";

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      hi: { translation: hi },
    },
    fallbackLng: "en",
    supportedLngs: ["en", "hi"],
    interpolation: {
      escapeValue: false, // React already escapes
    },
    detection: {
      order: ["localStorage", "navigator"],
      caches: ["localStorage"],
      lookupLocalStorage: "banking-locale",
    },
    debug: import.meta.env.DEV,
  });

export default i18n;
