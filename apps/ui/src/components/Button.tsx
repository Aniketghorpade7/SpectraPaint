import type { ButtonHTMLAttributes } from 'react';

/** A real `<button>`: a div with a click handler breaks keyboard use and screen readers. */
export function Button(props: ButtonHTMLAttributes<HTMLButtonElement>) {
  const { className, type = 'button', ...rest } = props;
  return (
    <button type={type} className={['button', className].filter(Boolean).join(' ')} {...rest} />
  );
}
