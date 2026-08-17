import localFont from "next/font/local";

export const Inter = localFont({
  src: [
    {
      path: "../../../public/fonts/InterVariable.woff2",
      weight: "100 900",
      style: "normal",
    },
    {
      path: "../../../public/fonts/InterVariable-Italic.woff2",
      weight: "100 900",
      style: "italic",
    },
  ],
  variable: "--font-inter",
  display: "swap",
});

export const InterDisplay = Inter;

export const Roboto = localFont({
  src: [
    {
      path: "../../../public/fonts/RobotoMono-Regular.ttf",
      weight: "400",
      style: "normal",
    },
    {
      path: "../../../public/fonts/RobotoMono-Bold.ttf",
      weight: "700",
      style: "normal",
    },
  ],
  variable: "--font-roboto-mono",
  display: "swap",
  // Reached only through the opt-in `font-roboto` utility, never as a body
  // font, so every page was preloading eight monospace files it would not
  // paint - which is what the browser's "preloaded but not used" warnings
  // were counting. `display: swap` still fades them in wherever they are used.
  preload: false,
});

export const Fustat = localFont({
  src: [
    {
      path: "../../../public/fonts/Fustat-VariableFont_wght.ttf",
      weight: "200 800",
      style: "normal",
    },
  ],
  variable: "--font-fustat",
  display: "swap",
});

export const DMMono = localFont({
  src: [
    {
      path: "../../../public/fonts/DMMono-Light.ttf",
      weight: "300",
      style: "normal",
    },
    {
      path: "../../../public/fonts/DMMono-LightItalic.ttf",
      weight: "300",
      style: "italic",
    },
    {
      path: "../../../public/fonts/DMMono-Regular.ttf",
      weight: "400",
      style: "normal",
    },
    {
      path: "../../../public/fonts/DMMono-Italic.ttf",
      weight: "400",
      style: "italic",
    },
    {
      path: "../../../public/fonts/DMMono-Medium.ttf",
      weight: "500",
      style: "normal",
    },
    {
      path: "../../../public/fonts/DMMono-MediumItalic.ttf",
      weight: "500",
      style: "italic",
    },
  ],
  variable: "--font-dm-mono",
  display: "swap",
  // Six faces behind the opt-in `font-dm-mono` utility. See Roboto above.
  preload: false,
});
