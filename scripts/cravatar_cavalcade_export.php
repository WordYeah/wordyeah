<?php
/**
 * Read-only Cavalcade metadata export for `wp eval-file`.
 *
 * This script performs one bounded SELECT and writes JSONL to stdout. It does
 * not fetch media or update WordPress, avatar state, or Cavalcade jobs.
 */

if ( ! defined( 'ABSPATH' ) ) {
	fwrite( STDERR, "Run with wp eval-file from the Cravatar WordPress root.\n" );
	exit( 1 );
}

global $wpdb;

$after_id = max( 0, (int) getenv( 'WORDYEAH_CRAVATAR_EXPORT_AFTER_ID' ) );
$limit    = min( 5000, max( 1, (int) ( getenv( 'WORDYEAH_CRAVATAR_EXPORT_LIMIT' ) ?: 500 ) ) );
$site_id  = max( 1, (int) ( getenv( 'WORDYEAH_CRAVATAR_SITE_ID' ) ?: 9 ) );
$since    = trim( (string) getenv( 'WORDYEAH_CRAVATAR_EXPORT_SINCE' ) );
$status   = trim( (string) ( getenv( 'WORDYEAH_CRAVATAR_EXPORT_STATUS' ) ?: 'completed' ) );

if ( ! in_array( $status, array( 'completed', 'failed', 'waiting', 'running' ), true ) ) {
	fwrite( STDERR, "Invalid export status.\n" );
	exit( 1 );
}
if ( '' !== $since && 1 !== preg_match( '/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/', $since ) ) {
	fwrite( STDERR, "Invalid export timestamp.\n" );
	exit( 1 );
}

$table       = $wpdb->base_prefix . 'cavalcade_jobs';
$since_where = '' !== $since ? ' AND start >= %s' : '';
$parameters  = array( $site_id, 'lpcn_sensitive_content_recognition', $status, $after_id );
if ( '' !== $since ) {
	$parameters[] = $since;
}
$parameters[] = $limit;

$sql = "SELECT id, status, start, args FROM {$table}
	WHERE site = %d AND hook = %s AND status = %s AND id > %d{$since_where}
	ORDER BY id ASC LIMIT %d";
$rows = $wpdb->get_results( $wpdb->prepare( $sql, $parameters ), ARRAY_A ); // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared

foreach ( $rows as $row ) {
	$data = maybe_unserialize( $row['args'] ?? null );
	if ( ! is_array( $data ) || ! isset( $data['url'], $data['image_md5'], $data['email_hash'] ) ) {
		continue;
	}
	$email_hash = strtolower( (string) $data['email_hash'] );
	$image_md5  = strtolower( (string) $data['image_md5'] );
	$url        = (string) $data['url'];
	if ( ! in_array( strlen( $email_hash ), array( 32, 64 ), true ) || ! ctype_xdigit( $email_hash ) ) {
		continue;
	}
	if ( 32 !== strlen( $image_md5 ) || ! ctype_xdigit( $image_md5 ) ) {
		continue;
	}
	if ( "https://cravatar.cn/avatar/{$email_hash}" !== $url ) {
		continue;
	}
	echo wp_json_encode(
		array(
			'source_id'      => 'cravatar-job:' . (int) $row['id'],
			'job_id'         => (int) $row['id'],
			'source_status'   => (string) $row['status'],
			'source_start'    => (string) $row['start'],
			'avatar_url'      => $url,
			'email_hash'      => $email_hash,
			'image_md5'       => $image_md5,
			'mutates_avatar'  => false,
		)
	) . "\n";
}
