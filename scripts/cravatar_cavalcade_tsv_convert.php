#!/usr/bin/env php
<?php
/**
 * Convert a read-only Cavalcade SQL TSV export into WordYeah JSONL.
 *
 * Expected columns: id, status, start, TO_BASE64(args). The remote query is
 * deliberately kept read-only; PHP serialized job arguments are decoded only
 * on the local operator machine.
 */

$input = $argv[1] ?? '';
if ( '' === $input || ! is_readable( $input ) ) {
	fwrite( STDERR, "Usage: cravatar_cavalcade_tsv_convert.php <export.tsv>\n" );
	exit( 2 );
}

$handle = fopen( $input, 'rb' );
if ( false === $handle ) {
	fwrite( STDERR, "Unable to open input.\n" );
	exit( 2 );
}

$seen = array();
$line = 0;
$current = null;

$emit = static function ( array $row, int $source_line ) use ( &$seen ): void {
	$job_id = filter_var( $row[0], FILTER_VALIDATE_INT, array( 'options' => array( 'min_range' => 1 ) ) );
	$status = (string) $row[1];
	$start = (string) $row[2];
	if ( false === $job_id || isset( $seen[ $job_id ] ) ) {
		fwrite( STDERR, "Invalid or duplicate job id at source line {$source_line}.\n" );
		exit( 1 );
	}
	if ( ! in_array( $status, array( 'completed', 'failed', 'waiting', 'running' ), true ) ) {
		fwrite( STDERR, "Invalid status at source line {$source_line}.\n" );
		exit( 1 );
	}

	$encoded = str_replace( '\\n', '', trim( (string) $row[3] ) );
	$serialized = base64_decode( $encoded, true );
	$data = false === $serialized ? false : @unserialize( $serialized, array( 'allowed_classes' => false ) );
	if ( ! is_array( $data ) || ! isset( $data['url'], $data['image_md5'], $data['email_hash'] ) ) {
		return;
	}

	$email_hash = strtolower( (string) $data['email_hash'] );
	$image_md5 = strtolower( (string) $data['image_md5'] );
	$url = (string) $data['url'];
	if ( ! in_array( strlen( $email_hash ), array( 32, 64 ), true ) || ! ctype_xdigit( $email_hash ) ) {
		return;
	}
	if ( 32 !== strlen( $image_md5 ) || ! ctype_xdigit( $image_md5 ) ) {
		return;
	}
	$accepted_urls = array(
		"https://cravatar.cn/avatar/{$email_hash}", // Legacy queue value; never emitted.
		"https://cravatar.com/avatar/{$email_hash}",
		"https://cn.cravatar.com/avatar/{$email_hash}",
	);
	if ( ! in_array( $url, $accepted_urls, true ) ) {
		return;
	}
	$url = "https://cravatar.com/avatar/{$email_hash}";

	$seen[ $job_id ] = true;
	echo json_encode(
		array(
			'source_id' => 'cravatar-job:' . $job_id,
			'job_id' => $job_id,
			'source_status' => $status,
			'source_start' => $start,
			'avatar_url' => $url,
			'email_hash' => $email_hash,
			'image_md5' => $image_md5,
			'mutates_avatar' => false,
		),
		JSON_UNESCAPED_SLASHES
	) . "\n";
};

while ( false !== ( $raw_line = fgets( $handle ) ) ) {
	++$line;
	$raw_line = rtrim( $raw_line, "\r\n" );
	if ( preg_match( '/^([1-9][0-9]*)\t(completed|failed|waiting|running)\t([^\t]*)\t(.*)$/', $raw_line, $match ) ) {
		if ( null !== $current ) {
			$emit( $current['row'], $current['line'] );
		}
		$current = array(
			'line' => $line,
			'row' => array( $match[1], $match[2], $match[3], $match[4] ),
		);
		continue;
	}
	if ( null === $current ) {
		if ( '' !== trim( $raw_line ) ) {
			fwrite( STDERR, "Invalid TSV content at source line {$line}.\n" );
			exit( 1 );
		}
		continue;
	}
	$current['row'][3] .= trim( $raw_line );
}
if ( null !== $current ) {
	$emit( $current['row'], $current['line'] );
}

fclose( $handle );
