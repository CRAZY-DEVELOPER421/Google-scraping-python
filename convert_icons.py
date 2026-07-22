#!/usr/bin/env python3
"""
Replace all inline SVGs in index.html with data-icon placeholders,
add the reusable icon() JS function, and update JS code to use it.
"""
import re

HTML_PATH = 'templates/index.html'

# ─── Canonical SVG Paths (strip width/height, use consistent viewBox) ───

ICONS = {
    'moon': '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
    'sun': '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>',
    'play': '<polygon points="5 3 19 12 5 21 5 3"/>',
    'bookmark': '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
    'check': '<polyline points="20 6 9 17 4 12"/>',
    'zap': '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    'search': '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    'search-smile': '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><path d="M7 11a4 4 0 0 1 8 0"/><path d="M8 14c0 0 1 2 3 2s3-2 3-2"/>',
    'clipboard': '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/>',
    'globe': '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
    'mail': '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/>',
    'camera': '<rect x="2" y="2" width="20" height="20" rx="5" ry="5"/><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"/><line x1="17.5" y1="6.5" x2="17.51" y2="6.5"/>',
    'linkedin': '<path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z"/><rect x="2" y="9" width="4" height="12"/><circle cx="4" cy="4" r="2"/>',
    'facebook': '<path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z"/>',
    'twitter': '<path d="M23 3a10.9 10.9 0 0 1-3.14 1.53 4.48 4.48 0 0 0-7.86 3v1A10.66 10.66 0 0 1 3 4s-4 9 5 13a11.64 11.64 0 0 1-7 2c9 5 20 0 20-11.5a4.5 4.5 0 0 0-.08-.83A7.72 7.72 0 0 0 23 3z"/>',
    'message-circle': '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>',
    'stop': '<rect x="6" y="6" width="12" height="12" rx="2" ry="2"/>',
    'trash': '<polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    'download': '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    'close': '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    'monitor': '<rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
    'chevron-left': '<polyline points="15 18 9 12 15 6"/>',
    'chevron-right': '<polyline points="9 18 15 12 9 6"/>',
    'folder': '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
    'clock': '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    'alert-triangle': '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    'check-circle': '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
    'error-x': '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>',
    'youtube': '<path d="M22.54 6.42a2.78 2.78 0 0 0-1.94-2C18.88 4 12 4 12 4s-6.88 0-8.6.46a2.78 2.78 0 0 0-1.94 2A29 29 0 0 0 1 11.75a29 29 0 0 0 .46 5.33A2.78 2.78 0 0 0 3.4 19c1.72.46 8.6.46 8.6.46s6.88 0 8.6-.46a2.78 2.78 0 0 0 1.94-2 29 29 0 0 0 .46-5.25 29 29 0 0 0-.46-5.33z"/><polygon points="9.75 15.02 15.5 11.75 9.75 8.48 9.75 15.02"/>',
    'tiktok': '<path d="M9 12a4 4 0 1 0 4 4V4h5c0 0 .5 3-2 4.5"/>',
    'telegram': '<path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/>',
    'pinterest': '<path d="M12 2C6.5 2 2 6.5 2 12c0 4.5 3.1 8.3 7.3 9.4-.1-.8-.2-2.1 0-3 .2-.9 1.4-5.9 1.4-5.9s-.4-.7-.4-1.8c0-1.7 1-3 2.2-3 .9 0 1.5.7 1.5 1.6 0 1-.6 2.5-1 3.9-.3 1.2.6 2.1 1.8 2.1 2.1 0 3.7-2.2 3.7-5.4 0-2.8-2-4.8-5-4.8-3.4 0-5.4 2.5-5.4 5.2 0 1 .4 2.1.9 2.7.1.1.1.2.1.4-.1.4-.3 1.2-.3 1.4 0 .2-.2.3-.4.2-1.5-.7-2.4-2.9-2.4-4.7 0-3.8 2.8-7.4 8.1-7.4 4.2 0 7.5 3 7.5 7.1 0 4.2-2.7 7.6-6.4 7.6-1.2 0-2.4-.6-2.8-1.4l-.8 3c-.3 1.1-1.1 2.5-1.6 3.3 1.2.4 2.5.6 3.8.6 5.5 0 10-4.5 10-10S17.5 2 12 2z"/>',
    'snapchat': '<path d="M18 8.5c0-3.3-2.7-6-6-6s-6 2.7-6 6c0 1.5.6 2.9 1.5 3.9-.2.2-.4.4-.5.5-.3.3-.4.7-.8.8-.3.1-.6-.1-1-.2-.5-.1-.9-.3-1.3-.2-.6.1-.8.4-.7.9.1.3.5.6 1 .9.5.3 1.1.6 1.5.8.4.2.7.6.8 1.1.1.3 0 .7.1 1 .1.4.4.6.9.7.3.1.6.2 1 .3.4.1.7.3.9.6.2.3.4.9.6 1.2.3.4.7.6 1.3.6s1.3-.9 1.7-.9 1.1.9 1.7.9c.6 0 .9-.2 1.3-.6.2-.3.4-.9.6-1.2.2-.3.5-.5.9-.6.4-.1.7-.2 1-.3.4-.1.7-.3.9-.7.1-.3 0-.7.1-1 .1-.5.4-.9.8-1.1.4-.2 1-.5 1.5-.8.5-.3.9-.6 1-.9.1-.5-.1-.8-.7-.9-.4-.1-.8.1-1.3.2-.4.1-.7.3-1 .2-.4-.1-.5-.5-.8-.8-.1-.1-.3-.3-.5-.5.9-1 1.5-2.4 1.5-3.9z"/>',
    'star': '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    'spinner': '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    'external-link': '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>',
}


def make_svg_pattern(name, content):
    """
    Build a regex pattern that matches an SVG containing the given path elements.
    The SVG may have any attributes (width, height, class, style, viewBox, etc.)
    and any whitespace.
    """
    # Escape the path content for regex
    # We need to match the SVG tag with any attributes, then the content (with possible whitespace variations)
    # Escape special regex chars in the content
    escaped = re.escape(content)
    # Allow flexible whitespace between elements
    escaped = escaped.replace(r'\ ', r'\s*')
    # Pattern: <svg ... attrs ...> ... whitespace ... content ... whitespace ... </svg>
    pattern = r'<svg[^>]*>\s*' + escaped + r'\s*</svg>'
    return pattern


def build_icon_mappings():
    """Build a list of (pattern, replacement) pairs for each icon."""
    mappings = []
    for name, content in ICONS.items():
        pattern = make_svg_pattern(name, content)
        # Replacement: data-icon placeholder
        # We'll detect if there's a class attribute we should preserve
        # For now, replacement with data-icon
        replacement = f'<span class="ico" data-ico="{name}"></span>'
        mappings.append((pattern, replacement, name))
    return mappings


def replace_in_html(content, mappings):
    """Apply all replacements to the HTML content."""
    stats = {name: 0 for _, _, name in mappings}
    
    for pattern, replacement, name in mappings:
        new_content, count = re.subn(pattern, replacement, content)
        if count > 0:
            print(f"  {name}: {count} replacement(s)")
            stats[name] = count
        content = new_content
    
    return content, stats


def write_icons_js():
    """Generate the JavaScript ICONS object and icon() function."""
    lines = []
    lines.append('        // ─── Reusable Icons ────────────────────────────')
    lines.append('        const ICONS = {')
    
    for name in sorted(ICONS.keys()):
        content = ICONS[name]
        lines.append(f"            '{name}': '{content}',")
    
    lines.append('        };')
    lines.append('')
    lines.append('        function icon(name, size) {')
    lines.append('            const content = ICONS[name];')
    lines.append('            if (!content) return "";')
    lines.append('            size = size || 16;')
    lines.append('            return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${content}</svg>`;')
    lines.append('        }')
    lines.append('')
    lines.append('        // Icons that need fill="currentColor" instead of stroke')
    lines.append('        const FILL_ICONS = new Set(["linkedin","facebook","twitter","star","tiktok","telegram","pinterest","snapchat","spinner"]);')
    lines.append('')
    lines.append('        function icon(name, size) {')
    lines.append('            const content = ICONS[name];')
    lines.append('            if (!content) return "";')
    lines.append('            size = size || 16;')
    lines.append('            const isFill = FILL_ICONS.has(name);')
    lines.append('            const fillAttr = isFill ? \\" fill=\\\\\\"currentColor\\\\\\" stroke=\\\\\\"none\\\\\\"\\" : \\" fill=\\\\\\"none\\\\\\" stroke=\\\\\\"currentColor\\\\\\" stroke-width=\\\\\\"2\\\\\\" stroke-linecap=\\\\\\"round\\\\\\" stroke-linejoin=\\\\\\"round\\\\\\"\\";')
    lines.append('            return `<svg width="\\${size}" height="\\${size}" viewBox="0 0 24 24"\\${fillAttr}>\\${content}</svg>`;')
    lines.append('        }')
    lines.append('')
    lines.append('        // Hydrate data-icon placeholders after DOM loads')
    lines.append('        document.addEventListener("DOMContentLoaded", () => {')
    lines.append('            document.querySelectorAll(".ico[data-ico]").forEach(el => {')
    lines.append('                const name = el.dataset.ico;')
    lines.append('                const size = parseInt(el.dataset.size) || 16;')
    lines.append('                el.innerHTML = icon(name, size);')
    lines.append('            });')
    lines.append('        });')
    
    return '\n'.join(lines)


def main():
    with open(HTML_PATH, 'r', encoding='utf-8') as f:
        content = f.read()
    
    print("Building icon mappings...")
    mappings = build_icon_mappings()
    
    print(f"Found {len(mappings)} icon patterns to replace")
    print("\nApplying replacements...")
    
    content_before = content
    content, stats = replace_in_html(content, mappings)
    
    total_replacements = sum(stats.values())
    print(f"\nTotal replacements made: {total_replacements}")
    
    if total_replacements == 0:
        print("No icons were matched. Something may be wrong with the patterns.")
        print("\nDebug: Let's check what the SVGs look like...")
        svgs = re.findall(r'<svg[^>]*>.*?</svg>', content_before, re.DOTALL)
        print(f"Found {len(svgs)} SVGs in the file.")
        # Try matching one by one manually
        for i, svg in enumerate(svgs[:5]):
            norm = re.sub(r'\s+', ' ', svg).strip()
            print(f"\nSVG {i+1}: {norm[:200]}...")
            for name, c in list(ICONS.items())[:5]:
                escaped = re.escape(c)
                escaped = escaped.replace(r'\ ', r'\s*')
                if re.search(escaped, norm):
                    print(f"  -> MATCHED: {name}")
        return
    
    # Write the modified content
    with open(HTML_PATH, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"\nWritten to {HTML_PATH}")
    print("\n⚠ WARNING: The JS icon() function and hydration script need to be")
    print("  manually added to the HTML file's <script> section!")
    print("  See the instructions below for what to add.")


if __name__ == '__main__':
    main()
