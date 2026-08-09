<?php
/**
 * Read-only keyset export for the Cravatar avatar registry.
 *
 * Run through `wp eval-file`. The script performs one bounded SELECT, emits
 * JSONL to stdout and never updates WordPress, Cavalcade or avatar state.
 */

if ( ! defined( 'ABSPATH' ) ) {
	fwrite( STDERR, "Run with wp eval-file from the Cravatar WordPress root.\n" );
	exit( 1 );
}

global $wpdb;

$after_value = getenv( 'WORDYEAH_CRAVATAR_EXPORT_AFTER_KEY' );
$has_after   = false !== $after_value;
$after_key   = strtolower( trim( (string) $after_value ) );
$max_value   = getenv( 'WORDYEAH_CRAVATAR_EXPORT_MAX_KEY' );
$has_max     = false !== $max_value && '' !== trim( (string) $max_value );
$max_key     = strtolower( trim( (string) $max_value ) );
$limit       = min( 5000, max( 1, (int) ( getenv( 'WORDYEAH_CRAVATAR_EXPORT_LIMIT' ) ?: 1000 ) ) );
$site_id     = max( 1, (int) ( getenv( 'WORDYEAH_CRAVATAR_SITE_ID' ) ?: 9 ) );
$table       = $wpdb->get_blog_prefix( $site_id ) . 'avatar_verify';

if ( $has_after && ( strlen( $after_key ) > 100 || preg_match( '/[^0-9a-f]/', $after_key ) ) ) {
	fwrite( STDERR, "Invalid keyset cursor.\n" );
	exit( 1 );
}
if ( $has_max && ( strlen( $max_key ) > 100 || preg_match( '/[^0-9a-f]/', $max_key ) ) ) {
	fwrite( STDERR, "Invalid snapshot maximum key.\n" );
	exit( 1 );
}

$clauses    = array( 'type IN (%s, %s)' );
$parameters = array( 'cravatar', 'gravatar' );
if ( $has_after ) {
	$clauses[]    = 'image_md5 > %s';
	$parameters[] = $after_key;
}
if ( $has_max ) {
	$clauses[]    = 'image_md5 <= %s';
	$parameters[] = $max_key;
}
$parameters[] = $limit;

$sql = "SELECT image_md5, url, type, hash_type, status FROM {$table}
	WHERE " . implode( ' AND ', $clauses ) . ' ORDER BY image_md5 ASC LIMIT %d';
$query_started = microtime( true );
$rows = $wpdb->get_results( $wpdb->prepare( $sql, $parameters ), ARRAY_A ); // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared
$query_elapsed = (int) round( ( microtime( true ) - $query_started ) * 1000 );
fwrite( STDERR, 'wordyeah_query_elapsed_ms=' . $query_elapsed . "\n" );

foreach ( $rows as $row ) {
	$registry_key = strtolower( trim( (string) ( $row['image_md5'] ?? '' ) ) );
	$origin       = strtolower( trim( (string) ( $row['type'] ?? '' ) ) );
	$hash_type    = strtolower( trim( (string) ( $row['hash_type'] ?? '' ) ) );
	$raw_url      = trim( (string) ( $row['url'] ?? '' ) );
	$email_hash   = '';
	$avatar_url   = null;
	$errors       = array();

	if ( 32 !== strlen( $registry_key ) || ! ctype_xdigit( $registry_key ) ) {
		$errors[] = 'invalid_registry_image_md5';
	}
	if ( ! in_array( $origin, array( 'cravatar', 'gravatar' ), true ) ) {
		$errors[] = 'invalid_avatar_origin';
	}
	if ( ! in_array( $hash_type, array( 'md5', 'sha256' ), true ) ) {
		$errors[] = 'invalid_hash_type';
	}
	$parts = wp_parse_url( $raw_url );
	$allowed_hosts = array( 'cravatar.cn', 'cravatar.com', 'cn.cravatar.com' );
	if (
		! is_array( $parts )
		|| 'https' !== ( $parts['scheme'] ?? '' )
		|| ! in_array( strtolower( (string) ( $parts['host'] ?? '' ) ), $allowed_hosts, true )
		|| isset( $parts['port'] )
		|| isset( $parts['user'] )
		|| isset( $parts['pass'] )
		|| isset( $parts['query'] )
		|| isset( $parts['fragment'] )
	) {
		$errors[] = 'invalid_avatar_url';
	} else {
		$path = (string) ( $parts['path'] ?? '' );
		if ( 1 === preg_match( '#^/avatar/([0-9a-fA-F]{32}|[0-9a-fA-F]{64})$#', $path, $matches ) ) {
			$email_hash = strtolower( $matches[1] );
			$expected    = 'sha256' === $hash_type ? 64 : 32;
			if ( strlen( $email_hash ) !== $expected ) {
				$errors[] = 'url_hash_type_mismatch';
			} else {
				$avatar_url = 'https://cravatar.com/avatar/' . $email_hash;
			}
		} else {
			$errors[] = 'invalid_avatar_path';
		}
	}

	echo wp_json_encode(
		array(
			'registry_key'   => $registry_key,
			'image_md5'      => $registry_key,
			'email_hash'     => $email_hash ?: null,
			'avatar_url'     => $avatar_url,
			'avatar_origin'  => $origin,
			'registry_status'=> isset( $row['status'] ) ? (int) $row['status'] : null,
			'hash_type'      => $hash_type,
			'metadata_valid' => empty( $errors ),
			'errors'         => $errors,
			'mutates_avatar' => false,
		)
	) . "\n";
}
