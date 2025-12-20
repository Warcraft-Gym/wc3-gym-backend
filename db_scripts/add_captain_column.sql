-- Add coach columns to team_season table
-- Coaches are team leaders/organizers (up to 3 per team per season)

ALTER TABLE team_season 
ADD COLUMN coach_1_id INT NULL,
ADD COLUMN coach_2_id INT NULL,
ADD COLUMN coach_3_id INT NULL,
ADD FOREIGN KEY (coach_1_id) REFERENCES users(id) ON DELETE SET NULL,
ADD FOREIGN KEY (coach_2_id) REFERENCES users(id) ON DELETE SET NULL,
ADD FOREIGN KEY (coach_3_id) REFERENCES users(id) ON DELETE SET NULL;

