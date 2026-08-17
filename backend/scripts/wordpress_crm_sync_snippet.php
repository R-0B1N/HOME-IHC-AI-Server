<?php
/**
 * Optimized WordPress Snippet: Real-Time & Bulk Sync to BentongLand CRM Backend
 * 
 * Instructions:
 * 1. Go to WordPress Admin -> WPCode -> Add Snippet -> Add Your Custom Code (PHP Snippet).
 * 2. Paste this entire code into the code box.
 * 3. Set Code Type to "PHP Snippet", Active: ON, and click "Save Snippet".
 */

// Define CRM Backend Webhook URL
if (!defined('CRM_WEBHOOK_URL')) {
    define('CRM_WEBHOOK_URL', 'https://database.bentongland.com.my/api/v1/wordpress/property');
}

// 1. Hook into Post Save / Publish / Update
add_action('save_post', 'sync_bentongland_to_crm', 20, 3);
add_action('wp_trash_post', 'sync_bentongland_trash_to_crm');

function sync_bentongland_to_crm($post_id, $post, $update) {
    // Prevent recursion
    static $is_syncing = false;
    if ($is_syncing) return;

    // Avoid autosaves, revisions, or auto-drafts
    if (defined('DOING_AUTOSAVE') && DOING_AUTOSAVE) return;
    if (wp_is_post_revision($post_id) || wp_is_post_autosave($post_id)) return;
    if ($post->post_status === 'auto-draft') return;

    // Allowed listing post types (BentongLand uses 'land', also support 'property' and 'post')
    $allowed_post_types = array('land', 'property', 'listing', 'post');
    if (!in_array($post->post_type, $allowed_post_types)) {
        return;
    }

    $is_syncing = true;

    // Determine Listing Status
    $status = 'Available';
    if ($post->post_status === 'trash') {
        $status = 'Inactive';
    } elseif ($post->post_status === 'draft') {
        $status = 'Draft';
    } elseif ($post->post_status === 'pending') {
        $status = 'Pending';
    } elseif (stripos($post->post_title, 'for rent') !== false) {
        $status = 'For Rent';
    } elseif (stripos($post->post_title, 'for sale') !== false) {
        $status = 'For Sale';
    }

    // Extract Featured Image
    $image_urls = array();
    $thumbnail_id = get_post_thumbnail_id($post_id);
    if ($thumbnail_id) {
        $feat_img = wp_get_attachment_image_url($thumbnail_id, 'full');
        if ($feat_img) {
            $image_urls[] = $feat_img;
        }
    }

    // Extract Gallery / Content Images if available
    if (preg_match_all('/<img[^>]+src=["\']([^"\']+)["\']/i', $post->post_content, $matches)) {
        foreach ($matches[1] as $img_src) {
            if (!in_array($img_src, $image_urls) && !strpos($img_src, 'logo') && !strpos($img_src, 'favicon')) {
                $image_urls[] = $img_src;
            }
        }
    }

    // Extract Taxonomies
    $categories = wp_get_post_terms($post_id, array('category-land', 'category', 'land_category'), array('fields' => 'names'));
    $cities = wp_get_post_terms($post_id, array('location-land', 'location', 'city'), array('fields' => 'names'));
    $states = wp_get_post_terms($post_id, array('state'), array('fields' => 'names'));
    $tenures = wp_get_post_terms($post_id, array('title-type', 'tenure'), array('fields' => 'names'));

    $city = !empty($cities) && !is_wp_error($cities) ? $cities[0] : 'Bentong';
    $state = !empty($states) && !is_wp_error($states) ? $states[0] : 'Pahang';
    $tenure = !empty($tenures) && !is_wp_error($tenures) ? $tenures[0] : 'Freehold';
    $category_list = !empty($categories) && !is_wp_error($categories) ? $categories : array('Agricultural Land');

    // Extract Meta Fields / ACF if set
    $price = get_post_meta($post_id, 'price', true) ?: get_post_meta($post_id, '_price', true);
    $acres = get_post_meta($post_id, 'acres', true) ?: get_post_meta($post_id, 'land_area', true);
    $built_up = get_post_meta($post_id, 'built_up', true) ?: get_post_meta($post_id, 'built_up_sqft', true);

    // Fallback price parsing from title/content if meta not found
    if (!$price) {
        if (preg_match('/RM\s*([\d\.,]+)\s*(?:million|mil|m\b)/i', $post->post_title . ' ' . $post->post_content, $m)) {
            $price = floatval(str_replace(',', '', $m[1])) * 1000000;
        } elseif (preg_match('/RM\s*([\d\.,]+)\s*(?:k\b)/i', $post->post_title . ' ' . $post->post_content, $m)) {
            $price = floatval(str_replace(',', '', $m[1])) * 1000;
        } elseif (preg_match('/RM\s*([\d,]+)/i', $post->post_title . ' ' . $post->post_content, $m)) {
            $price = floatval(str_replace(',', '', $m[1]));
        }
    }

    // Fallback acres parsing
    if (!$acres) {
        if (preg_match('/([\d\.]+)\s*(?:acres?|ac\b|ekar)/i', $post->post_title . ' ' . $post->post_content, $m)) {
            $acres = floatval($m[1]);
        }
    }

    $payload = array(
        'title'                   => $post->post_title,
        'description'             => wp_strip_all_tags($post->post_content),
        'source_url'              => get_permalink($post_id),
        'status'                  => $status,
        'asking_price_myr'        => floatval($price) ?: 0.0,
        'land_area_acres'         => floatval($acres) ?: 0.0,
        'built_up_area_sqft'      => floatval($built_up) ?: 0.0,
        'city'                    => $city,
        'state'                   => $state,
        'tenure'                  => $tenure,
        'category'                => $category_list,
        'image_urls'              => $image_urls,
        'wp_post_id'              => $post_id,
        'updated_at'              => current_time('mysql'),
    );

    // Dispatch webhook to CRM Backend
    $response = wp_remote_post(CRM_WEBHOOK_URL, array(
        'method'      => 'POST',
        'timeout'     => 15,
        'redirection' => 5,
        'httpversion' => '1.1',
        'blocking'    => false, // Asynchronous non-blocking to prevent WP save lag
        'headers'     => array('Content-Type' => 'application/json'),
        'body'        => wp_json_encode($payload),
    ));

    $is_syncing = false;
}

// 2. Hook into Trashed Posts
function sync_bentongland_trash_to_crm($post_id) {
    $post = get_post($post_id);
    if ($post && in_array($post->post_type, array('land', 'property', 'listing', 'post'))) {
        sync_bentongland_to_crm($post_id, $post, true);
    }
}
