ALTER TABLE profiles ADD COLUMN IF NOT EXISTS voice_id text NOT NULL DEFAULT 'JBFqnCBsd6RMkjVDRZzb';
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS voice_tone text NOT NULL DEFAULT 'calm';
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS voice_profile_code text;
CREATE UNIQUE INDEX IF NOT EXISTS profiles_voice_code ON profiles (voice_profile_code) WHERE voice_profile_code IS NOT NULL;
