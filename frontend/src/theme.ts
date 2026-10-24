import {
  Button, createTheme, defaultVariantColorsResolver, Drawer, Input, InputWrapper, Menu, Modal, Notification,
  type MantineColorsTuple, type VariantColorsResolver,
} from '@mantine/core';

const aeza: MantineColorsTuple = ['#e6f8fe', '#ccf0fc', '#9fe2f9', '#6fd3f5', '#4cc6f1', '#2fb9ea', '#14a6d9', '#0b8bb8', '#0b6c96', '#084e6d'];

const resolver: VariantColorsResolver = (input) => {
  const danger = input.color === 'red';
  const tone = danger ? 'var(--red)' : 'var(--accent)';
  const soft = danger ? 'var(--red-soft)' : 'var(--blue-soft)';
  switch (input.variant) {
    case 'filled':
      return { background: tone, hover: danger ? 'var(--red)' : 'var(--accent-2)', color: danger ? 'var(--paper)' : 'var(--on-accent)', border: '1.5px solid transparent' };
    case 'outline':
      return { background: 'transparent', hover: soft, color: tone, border: `1.5px solid ${tone}` };
    case 'subtle':
      return { background: 'transparent', hover: danger ? soft : 'var(--paper-2)', color: danger ? tone : 'var(--ink)', border: '1.5px solid transparent' };
    case 'transparent':
      return { background: 'transparent', hover: 'transparent', color: danger ? tone : 'var(--blue-ink)', border: '1.5px solid transparent' };
    default:
      return defaultVariantColorsResolver(input);
  }
};

export const theme = createTheme({
  primaryColor: 'aeza',
  colors: { aeza },
  primaryShade: { light: 8, dark: 4 },
  fontFamily: "'Inter', 'Helvetica Neue', Arial, sans-serif",
  fontFamilyMonospace: "ui-monospace, 'SF Mono', Menlo, monospace",
  headings: { fontFamily: "'Exo 2', 'Inter', sans-serif", fontWeight: '800' },
  defaultRadius: 'sm',
  radius: { xs: '6px', sm: '10px', md: '14px' },
  fontSizes: { sm: '15px', md: '16px' },
  variantColorResolver: resolver,
  components: {
    Button: Button.extend({ defaultProps: { size: 'sm', radius: 'sm' }, classNames: { root: 'ik-btn' } }),
    Input: Input.extend({ classNames: { input: 'ik-input', section: 'ik-section' } }),
    InputWrapper: InputWrapper.extend({ classNames: { label: 'ik-label', description: 'ik-hint', error: 'ik-error' } }),
    Modal: Modal.extend({
      defaultProps: { centered: true, size: 520, overlayProps: { backgroundOpacity: 1 } },
      classNames: { content: 'ik-modal-content', header: 'ik-modal-header', title: 'ik-modal-title', overlay: 'ik-overlay' },
    }),
    Drawer: Drawer.extend({
      defaultProps: { position: 'right', size: 560, overlayProps: { backgroundOpacity: 1 } },
      classNames: { content: 'ik-drawer-content', header: 'ik-drawer-header', overlay: 'ik-overlay' },
    }),
    Menu: Menu.extend({ defaultProps: { shadow: 'md', position: 'bottom-end' }, classNames: { dropdown: 'ik-menu', item: 'ik-menu-item' } }),
    Notification: Notification.extend({
      classNames: { root: 'ik-notification', title: 'ik-notification-title', description: 'ik-notification-description', closeButton: 'ik-notification-close' },
    }),
  },
});
