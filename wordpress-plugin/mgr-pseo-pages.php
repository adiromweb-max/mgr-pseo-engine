<?php
/**
 * Plugin Name: MGR pSEO Pages
 * Description: Registers the programmatic SEO custom post type for MiniGoldenRetrievers.com. Pages inherit the active theme (YOOtheme) and are pushed in by the external generation engine via REST.
 * Version: 1.0
 * Author: A-WEB Marketing
 */

if (!defined('ABSPATH')) exit;

/**
 * Register the mgr_page custom post type.
 * - public + has_archive so pages get real URLs and enter sitemaps
 * - show_in_rest = true so the Python engine can push via REST API
 * - rewrite slug kept clean; individual slugs set per-page by the engine
 */
add_action('init', function () {
    register_post_type('mgr_page', [
        'labels' => [
            'name'          => 'MGR Pages',
            'singular_name' => 'MGR Page',
            'add_new_item'  => 'Add New MGR Page',
            'edit_item'     => 'Edit MGR Page',
        ],
        'public'       => true,
        'has_archive'  => false,
        'show_ui'      => true,
        'show_in_rest' => true,                       // REQUIRED for REST push
        'rest_base'    => 'mgr_page',
        'menu_icon'    => 'dashicons-pets',
        'supports'     => ['title', 'editor', 'excerpt', 'custom-fields', 'thumbnail'],
        'rewrite'      => ['slug' => '', 'with_front' => false], // root-level clean URLs
    ]);
});

/**
 * Register custom REST meta fields so the engine can set SEO title,
 * meta description, schema JSON, and the keyword-owner mapping.
 */
add_action('init', function () {
    foreach (['mgr_seo_title', 'mgr_meta_desc', 'mgr_schema', 'mgr_intent', 'mgr_location', 'mgr_owner_keyword'] as $key) {
        register_post_meta('mgr_page', $key, [
            'show_in_rest' => true,
            'single'       => true,
            'type'         => 'string',
            'auth_callback'=> function () { return current_user_can('edit_posts'); },
        ]);
    }
});

/**
 * Output SEO meta + schema in <head> for mgr_page singles.
 * Works alongside Yoast/RankMath; only fills our CPT.
 */
add_action('wp_head', function () {
    if (!is_singular('mgr_page')) return;
    $id   = get_the_ID();
    $desc = get_post_meta($id, 'mgr_meta_desc', true);
    $title= get_post_meta($id, 'mgr_seo_title', true);
    $schema = get_post_meta($id, 'mgr_schema', true);
    if ($desc)  echo '<meta name="description" content="' . esc_attr($desc) . '">' . "\n";
    if ($title) echo '<meta property="og:title" content="' . esc_attr($title) . '">' . "\n";
    if ($schema) echo '<script type="application/ld+json">' . $schema . '</script>' . "\n";
}, 1);

/**
 * Use the SEO title for <title> if set.
 */
add_filter('document_title_parts', function ($parts) {
    if (is_singular('mgr_page')) {
        $t = get_post_meta(get_the_ID(), 'mgr_seo_title', true);
        if ($t) $parts['title'] = $t;
    }
    return $parts;
});

/**
 * Flush rewrite rules on activation so clean URLs work immediately.
 */
register_activation_hook(__FILE__, function () {
    flush_rewrite_rules();
});
register_deactivation_hook(__FILE__, function () {
    flush_rewrite_rules();
});
