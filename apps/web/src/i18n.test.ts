import { describe, expect, it } from "vitest";
import { fmtInt, fmtMoney, resolveLang, setLang, t } from "./i18n";
import en from "./locales/en";
import pt from "./locales/pt";

/** `{n}`, `{pct}`, ... in a message, as a set. */
function placeholders(message: string): Set<string> {
  return new Set(
    Array.from(message.matchAll(/\{(\w+)\}/g), (match) => match[1]),
  );
}

describe("catalogs", () => {
  // A missing or extra KEY is already a compile error (pt.ts is typed against
  // en.ts). A dropped PLACEHOLDER is not: the message still renders, just
  // silently without the number in it.
  it("use the same placeholders in both languages", () => {
    for (const key of Object.keys(en) as (keyof typeof en)[]) {
      expect([key, [...placeholders(pt[key])].sort()]).toEqual([
        key,
        [...placeholders(en[key])].sort(),
      ]);
    }
  });
});

describe("t", () => {
  it("renders the language the channel speaks", () => {
    setLang("pt-BR");
    expect(t("app.nav.channel")).toBe("Meu canal");
    setLang("en-GB");
    expect(t("app.nav.channel")).toBe("My channel");
  });

  it("fills placeholders and leaves unknown ones alone", () => {
    setLang("en");
    expect(t("chatters.page", { page: 2, total: 7 })).toBe("page 2 of 7");
    expect(t("chatters.page", { page: 2 })).toBe("page 2 of {total}");
  });
});

describe("resolveLang", () => {
  it("treats anything that is not Portuguese as English", () => {
    expect(resolveLang("pt")).toBe("pt");
    expect(resolveLang("PT-br")).toBe("pt");
    expect(resolveLang("en")).toBe("en");
    expect(resolveLang("es")).toBe("en");
    expect(resolveLang(null)).toBe("en");
  });
});

describe("number formatting", () => {
  it("follows the screen language", () => {
    setLang("en");
    expect(fmtInt(12400)).toBe("12,400");
    expect(fmtMoney(546)).toBe("$546.00");
    setLang("pt");
    expect(fmtInt(12400)).toBe("12.400");
    expect(fmtMoney(546)).toContain("546,00");
  });
});
