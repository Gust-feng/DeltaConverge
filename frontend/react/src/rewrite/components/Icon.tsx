import type { CSSProperties } from "react";

type IconProps = {
  name: string;
  className?: string;
  style?: CSSProperties;
  /** 旧版手写的 <svg class="icon"> 不带 icon-${name} 类，传 true 可精确复刻。 */
  plain?: boolean;
};

/**
 * 图标统一走 index.html 里的 SVG sprite，形状与旧版完全一致。
 * 旧版 getIcon() 生成的是 class="icon icon-${name}"，因此默认保留该组合。
 */
export function Icon({ name, className, style, plain = false }: IconProps) {
  const classes = plain
    ? ["icon", className].filter(Boolean).join(" ")
    : ["icon", `icon-${name}`, className].filter(Boolean).join(" ");
  return (
    <svg className={classes} style={style}>
      <use href={`#icon-${name}`} />
    </svg>
  );
}
