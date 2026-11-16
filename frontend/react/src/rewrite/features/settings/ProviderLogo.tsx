/** 本地品牌资产，来源与许可证见 public/assets/providers/LICENSE.lobe-icons.txt。 */
import { PROVIDER_CATALOG } from "./providerCatalog";

export function ProviderLogo({
  provider,
  size = "md",
}: {
  provider: string;
  label: string;
  size?: "xs" | "sm" | "md" | "lg";
}) {
  const logo = PROVIDER_CATALOG[provider.toLowerCase()]?.logo;
  const src = logo ? `/assets/providers/${logo}` : undefined;

  return (
    <span className={`ds-logo ds-logo--${size}`} aria-hidden="true">
      {src ? <img src={src} alt="" loading="lazy" /> : (
        <svg width="62%" height="62%" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="9" /><path d="M12 6v6l4 2" />
        </svg>
      )}
    </span>
  );
}
